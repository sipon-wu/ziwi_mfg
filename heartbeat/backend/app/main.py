"""
Heartbeat Service — Ziwi License Heartbeat Monitor.

Receives periodic heartbeats from deployment instances (school / mfg),
monitors online status, manages License authority, and syncs license
state back to clients via license_update in heartbeat response.

Phase 2 — License authority integrated (2026-07-27).
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("heartbeat")

# ============================================================
# Config
# ============================================================


class Settings(BaseSettings):
    """Application settings, loaded from HEARTBEAT_* env vars or .env file."""

    api_key: str = "changeme-dev-key"
    database_path: str = "data/heartbeat.db"
    port: int = 8091
    heartbeat_timeout_minutes: int = 15
    offline_threshold_misses: int = 3
    check_interval_minutes: int = 5
    license_warn_days: int = 30
    license_critical_days: int = 7

    model_config = {
        "env_prefix": "HEARTBEAT_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

# ============================================================
# Database engine & session
# ============================================================

# Ensure data directory exists
_db_dir = os.path.dirname(settings.database_path)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{settings.database_path}"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


# ============================================================
# Models
# ============================================================


class Deployment(Base):
    """Represents a registered deployment instance (mfg / school)."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[str] = mapped_column(
        String(32), nullable=False, default=""
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    license_issued_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    license_expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="offline"
    )
    consecutive_misses: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        """Serialize deployment to a plain dict for API responses."""
        return {
            "deployment_id": self.deployment_id,
            "tenant_id": self.tenant_id,
            "product": self.product,
            "version": self.version,
            "license_issued_at": self.license_issued_at,
            "license_expires_at": self.license_expires_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "status": self.status,
            "consecutive_misses": self.consecutive_misses,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class License(Base):
    """
    License authority — authoritative source of license state for each tenant+product.

    Set by admin API (POST /api/v1/admin/licenses). Auto-seeded from school's
    first heartbeat if no record exists. Heartbeat response includes
    `license_update` derived from this table.
    """

    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    product: Mapped[str] = mapped_column(String(32), nullable=False, default="school")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none"
    )  # active | trial | none
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "product": self.product,
            "status": self.status,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ============================================================
# Pydantic Schemas
# ============================================================


class HeartbeatRequest(BaseModel):
    """
    Payload sent by a deployment instance on each heartbeat.

    Supports both mfg format (with deployment_id) and school format
    (without deployment_id — auto-generated from tenant_id + product).
    """

    deployment_id: str = Field(
        default="", max_length=64, description="Unique deployment ID; auto-generated if empty"
    )
    tenant_id: str = Field(..., max_length=64, description="Owning tenant ID")
    product: str = Field(..., max_length=32, description="Product: mfg or school")
    version: str = Field(default="", max_length=32, description="Software version")
    license_issued_at: Optional[datetime] = Field(
        default=None, description="License issue date (required for new mfg deployments)"
    )
    license_expires_at: Optional[datetime] = Field(
        default=None, description="License expiry date"
    )
    # school-specific fields (ignored by mfg client)
    license_status: Optional[str] = Field(
        default=None, max_length=16, description="License status reported by client"
    )
    school_name: Optional[str] = Field(
        default=None, max_length=128, description="School display name"
    )


class HeartbeatResponse(BaseModel):
    """Response returned after a heartbeat is processed."""

    status: str
    deployment_id: str
    license_update: Optional[dict] = None


class LicenseCreate(BaseModel):
    """Admin payload to create or update a License record."""

    tenant_id: str = Field(..., max_length=64, description="Tenant ID")
    product: str = Field(default="school", max_length=32)
    status: str = Field(..., max_length=16, description="active / trial / none")
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class LicenseResponse(BaseModel):
    """License record returned to admin."""

    tenant_id: str
    product: str
    status: str
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ============================================================
# Dependencies
# ============================================================


def get_db():
    """FastAPI dependency: yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_api_key(x_api_key: str = Header(default=None, alias="X-Api-Key")):
    """FastAPI dependency: validates the X-Api-Key header."""
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
    return x_api_key


# ============================================================
# License helpers
# ============================================================


def _lookup_license(db: Session, tenant_id: str, product: str) -> Optional[License]:
    """Look up License record by tenant_id + product."""
    return (
        db.query(License)
        .filter(License.tenant_id == tenant_id, License.product == product)
        .first()
    )


def _build_license_update(lic: License) -> Optional[dict]:
    """Build license_update dict from License record, or None if status=none."""
    if lic.status == "none":
        return None
    d: dict = {"status": lic.status}
    if lic.expires_at:
        if lic.expires_at.tzinfo is None:
            d["expires_at"] = lic.expires_at.replace(tzinfo=timezone.utc).isoformat()
        else:
            d["expires_at"] = lic.expires_at.isoformat()
    return d


# ============================================================
# APScheduler Background Task
# ============================================================

scheduler = BackgroundScheduler()


def check_deployments():
    """
    Periodic job executed every N minutes.

    - Scans for deployments whose last_heartbeat_at is older than the timeout.
    - Increments consecutive_misses; if >= threshold, marks deployment offline.
    - Also checks never-beat deployments created beyond the timeout window.
    - License expiry alerts are computed on-demand in GET /api/v1/alerts.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        timeout_threshold = now - timedelta(
            minutes=settings.heartbeat_timeout_minutes
        )

        # ---- stale heartbeats ----
        stale = (
            db.query(Deployment)
            .filter(
                Deployment.last_heartbeat_at.isnot(None),
                Deployment.last_heartbeat_at < timeout_threshold,
            )
            .all()
        )

        for dep in stale:
            dep.consecutive_misses += 1
            if dep.consecutive_misses >= settings.offline_threshold_misses:
                if dep.status != "offline":
                    dep.status = "offline"
                    logger.warning(
                        "Deployment %s marked OFFLINE after %d missed heartbeats",
                        dep.deployment_id,
                        dep.consecutive_misses,
                    )

        # ---- never-heard-from ----
        never = (
            db.query(Deployment)
            .filter(Deployment.last_heartbeat_at.is_(None))
            .all()
        )

        for dep in never:
            if dep.created_at < timeout_threshold:
                dep.consecutive_misses += 1
                if dep.consecutive_misses >= settings.offline_threshold_misses:
                    if dep.status != "offline":
                        dep.status = "offline"
                        logger.warning(
                            "Deployment %s marked OFFLINE (never reported in)",
                            dep.deployment_id,
                        )

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Scheduler check failed")
    finally:
        db.close()


# ============================================================
# FastAPI Application
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables & launch scheduler.  Shutdown: stop scheduler."""
    Base.metadata.create_all(bind=engine)
    scheduler.add_job(
        check_deployments,
        trigger=IntervalTrigger(minutes=settings.check_interval_minutes),
        id="check_deployments",
        name="Check offline deployments",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Heartbeat service started (port=%d, check_interval=%d min)",
        settings.port,
        settings.check_interval_minutes,
    )
    yield
    scheduler.shutdown(wait=False)
    logger.info("Heartbeat service stopped")


app = FastAPI(
    title="Ziwi Heartbeat Service",
    version="1.2.0",
    lifespan=lifespan,
)

# ============================================================
# Routes — Public / Heartbeat
# ============================================================


@app.get("/health")
def health():
    """Health-check endpoint (no auth required)."""
    return {"status": "ok", "service": "heartbeat"}


@app.post(
    "/api/v1/heartbeat",
    status_code=status.HTTP_200_OK,
    response_model=HeartbeatResponse,
)
def heartbeat_post(
    req: HeartbeatRequest,
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Receive a heartbeat from a deployment instance.

    Supports two payload formats:
    - mfg format: includes deployment_id, license_issued_at, license_expires_at
    - school format: no deployment_id (auto-generated), includes license_status

    After updating deployment state, looks up the License authority record
    for this tenant and returns license_update in the response.
    """
    now = datetime.now(timezone.utc)

    # --- resolve / auto-generate deployment_id ---
    deployment_id = req.deployment_id
    if not deployment_id:
        deployment_id = f"{req.product}-{req.tenant_id}"

    dep = (
        db.query(Deployment)
        .filter(Deployment.deployment_id == deployment_id)
        .first()
    )

    if dep is None:
        # --- create new deployment ---
        if req.license_issued_at is None and req.license_expires_at is None:
            # school format: no license timestamps required; use now as fallback
            issued = now
            expires = now + timedelta(days=365)
        else:
            issued = req.license_issued_at or now
            expires = req.license_expires_at or (now + timedelta(days=365))

        dep = Deployment(
            deployment_id=deployment_id,
            tenant_id=req.tenant_id,
            product=req.product,
            version=req.version,
            license_issued_at=issued,
            license_expires_at=expires,
            last_heartbeat_at=now,
            status="online",
            consecutive_misses=0,
        )
        db.add(dep)
        db.commit()
        db.refresh(dep)
        logger.info("New deployment registered: %s (product=%s)", deployment_id, req.product)
        resp_status = "created"
    else:
        # --- update existing deployment ---
        dep.last_heartbeat_at = now
        dep.consecutive_misses = 0
        dep.status = "online"
        dep.version = req.version or dep.version
        dep.tenant_id = req.tenant_id or dep.tenant_id
        dep.product = req.product or dep.product
        dep.updated_at = now
        db.commit()
        resp_status = "updated"

    # --- License authority: auto-seed if school reports state with no existing record ---
    lic = _lookup_license(db, req.tenant_id, req.product)
    if lic is None and req.license_status:
        # Auto-seed from school's reported state
        lic = License(
            tenant_id=req.tenant_id,
            product=req.product,
            status=req.license_status,
            expires_at=req.license_expires_at,
        )
        db.add(lic)
        db.commit()
        db.refresh(lic)
        logger.info(
            "License auto-seeded for tenant=%s product=%s status=%s",
            req.tenant_id, req.product, req.license_status,
        )

    # --- build response with license_update ---
    response = HeartbeatResponse(
        status=resp_status,
        deployment_id=deployment_id,
    )
    if lic:
        lu = _build_license_update(lic)
        if lu:
            response.license_update = lu

    return response


# ============================================================
# Routes — Deployment Status
# ============================================================


@app.get("/api/v1/status")
def list_status(
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """List all registered deployment statuses, newest first."""
    deployments = (
        db.query(Deployment)
        .order_by(Deployment.updated_at.desc())
        .all()
    )
    return [d.to_dict() for d in deployments]


@app.get("/api/v1/status/{deployment_id}")
def get_status(
    deployment_id: str,
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get status for a single deployment by its deployment_id."""
    dep = (
        db.query(Deployment)
        .filter(Deployment.deployment_id == deployment_id)
        .first()
    )
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    return dep.to_dict()


# ============================================================
# Routes — License Admin API
# ============================================================


@app.post("/api/v1/admin/licenses", status_code=status.HTTP_201_CREATED)
def create_license(
    body: LicenseCreate,
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Create or update a License record (authoritative source).

    Idempotent: if tenant_id already exists, updates status/expiry in place.
    """
    lic = (
        db.query(License)
        .filter(License.tenant_id == body.tenant_id)
        .first()
    )
    now = datetime.now(timezone.utc)
    if lic is None:
        lic = License(
            tenant_id=body.tenant_id,
            product=body.product,
            status=body.status,
            issued_at=body.issued_at or now,
            expires_at=body.expires_at,
        )
        db.add(lic)
        db.commit()
        db.refresh(lic)
        logger.info("License created: tenant=%s status=%s", body.tenant_id, body.status)
        return {"status": "created", **lic.to_dict()}
    else:
        lic.status = body.status
        lic.product = body.product or lic.product
        if body.issued_at is not None:
            lic.issued_at = body.issued_at
        lic.expires_at = body.expires_at
        lic.updated_at = now
        db.commit()
        logger.info("License updated: tenant=%s status=%s", body.tenant_id, body.status)
        return {"status": "updated", **lic.to_dict()}


@app.get("/api/v1/admin/licenses")
def list_licenses(
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """List all License records."""
    licenses = db.query(License).order_by(License.updated_at.desc()).all()
    return [l.to_dict() for l in licenses]


@app.get("/api/v1/admin/licenses/{tenant_id}")
def get_license(
    tenant_id: str,
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get a single License record by tenant_id."""
    lic = (
        db.query(License)
        .filter(License.tenant_id == tenant_id)
        .first()
    )
    if lic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="License not found",
        )
    return lic.to_dict()


# ============================================================
# Routes — Admin Web UI
# ============================================================


@app.get("/admin", include_in_schema=False)
def admin_page(key: Optional[str] = None):
    """License management dashboard (HTML).

    Authenticate via ?key=<api_key> query param. If missing or wrong,
    shows a ToC-style login page. No X-Api-Key header needed.
    """
    api_key = settings.api_key
    validated = key == api_key

    LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>知微云 · 管理平台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter','PingFang SC','Microsoft YaHei',sans-serif;min-height:100vh;background:linear-gradient(135deg,#eff6ff,#e0e7ff);display:flex;align-items:center;justify-content:center;padding:24px}
.card{width:100%;max-width:400px;background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.06);padding:40px 36px 36px}
.brand{text-align:center;margin-bottom:32px}
.brand h1{font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:.5px}
.brand p{font-size:13px;color:#999;margin-top:4px}
.input-group{margin-bottom:20px}
.input-group label{display:block;font-size:13px;font-weight:500;color:#555;margin-bottom:6px}
.input-group input{width:100%;padding:11px 14px;border:1.5px solid #d1d5db;border-radius:10px;font-size:14px;color:#333;outline:none;transition:all .2s;background:#fff}
.input-group input::placeholder{color:#bbb}
.input-group input:focus{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.15)}
.submit-btn{width:100%;padding:11px;background:#2563eb;border:none;border-radius:10px;color:#fff;font-size:15px;font-weight:500;cursor:pointer;transition:all .15s}
.submit-btn:hover{background:#1d4ed8}
.submit-btn:active{transform:scale(.98)}
</style>
</head>
<body>
<div class="card">
  <div class="brand">
    <h1>知微云</h1>
    <p>管理平台</p>
  </div>
  <form onsubmit="event.preventDefault();var k=this.querySelector('input').value;if(k)location.href='/admin?key='+encodeURIComponent(k)">
    <div class="input-group">
      <label>管理密码</label>
      <input type="password" placeholder="请输入密码" autofocus>
    </div>
    <button class="submit-btn" type="submit">登录</button>
  </form>
</div>
</body>
</html>"""

    DASHBOARD_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>知微 · License 管理</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter','PingFang SC','Microsoft YaHei',sans-serif;background:#f0f2f6;color:#1a1a2e}
.topbar{background:#fff;border-bottom:1px solid #e8ecf1;padding:0 32px;height:60px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.topbar-left{display:flex;align-items:center;gap:12px}
.topbar-logo{width:32px;height:32px;background:#1a3a6b;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700}
.topbar-title{font-size:16px;font-weight:600;color:#1a1a2e}
.topbar-sub{font-size:12px;color:#999;margin-left:8px}
.topbar-right{display:flex;align-items:center;gap:16px}
.logout-link{font-size:13px;color:#888;text-decoration:none;padding:6px 14px;border-radius:6px;border:1px solid #e8ecf1;transition:all .2s}
.logout-link:hover{background:#f5f6fa;color:#1a3a6b}
.container{max-width:1280px;margin:0 auto;padding:24px 32px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:28px}
.stat{background:#fff;border-radius:12px;padding:18px 20px;box-shadow:0 1px 3px rgba(0,0,0,.04);border:1px solid #f0f2f5}
.stat-label{font-size:12px;color:#999;font-weight:500;text-transform:uppercase;letter-spacing:.3px}
.stat-value{font-size:28px;font-weight:700;color:#1a3a6b;margin-top:4px;line-height:1.2}
.stat-value.ok{color:#2d8a4e}
.stat-value.warn{color:#d48806}
.stat-value.danger{color:#cd201f}
.stat-sub{font-size:12px;color:#bbb;margin-top:2px}
.tabs{display:flex;gap:0;margin-bottom:0;border-bottom:1px solid #e8ecf1}
.tab{padding:12px 24px;cursor:pointer;font-size:14px;color:#666;border-bottom:2px solid transparent;transition:all .2s;font-weight:500}
.tab:hover{color:#1a3a6b}
.tab.active{border-bottom-color:#1a3a6b;color:#1a3a6b;font-weight:600}
.panel{background:#fff;border-radius:0 12px 12px 12px;box-shadow:0 1px 3px rgba(0,0,0,.04);border:1px solid #e8ecf1;border-top:none;padding:24px}
.panel-title{font-size:15px;font-weight:600;color:#1a1a2e;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.panel-title small{font-weight:400;font-size:12px;color:#999}
.form-row{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-bottom:20px;padding:16px;background:#f8f9fc;border-radius:10px;border:1px dashed #e8ecf1}
.form-group{display:flex;flex-direction:column}
.form-group label{font-size:11px;color:#888;font-weight:500;margin-bottom:4px;text-transform:uppercase;letter-spacing:.3px}
.form-group input,.form-group select{padding:8px 12px;border:1.5px solid #e8ecf1;border-radius:8px;font-size:13px;outline:none;background:#fff;transition:all .15s;color:#333}
.form-group input:focus,.form-group select:focus{border-color:#1a3a6b;box-shadow:0 0 0 3px rgba(26,58,107,.08)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:10px 12px;font-weight:600;color:#666;font-size:11px;text-transform:uppercase;letter-spacing:.3px;border-bottom:2px solid #e8ecf1;background:#fafbfc}
td{padding:10px 12px;border-bottom:1px solid #f0f2f5;color:#333}
tr:hover td{background:#f8f9fc}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:600}
.badge-active{background:#e6f7ed;color:#2d8a4e}
.badge-trial{background:#fff7e6;color:#d48806}
.badge-none{background:#f0f2f5;color:#999}
.badge-online{background:#e6f7ed;color:#2d8a4e}
.badge-offline{background:#fff0f0;color:#cd201f}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:7px 18px;border:none;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;transition:all .15s;color:#fff}
.btn-primary{background:#1a3a6b}
.btn-primary:hover{background:#14305a}
.btn-sm{padding:4px 12px;font-size:11px;border-radius:6px}
.btn-outline{background:transparent;border:1.5px solid #dcdfe6;color:#666}
.btn-outline:hover{border-color:#1a3a6b;color:#1a3a6b}
.alert-box{background:#fff;border-radius:10px;padding:14px 18px;margin-bottom:10px;border:1px solid #f0f2f5;border-left:4px solid #d48806;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.alert-box.critical{border-left-color:#cd201f}
.alert-box.info{border-left-color:#1a3a6b}
.alert-title{font-weight:600;font-size:13px;color:#333}
.alert-detail{font-size:12px;color:#999;margin-top:4px}
.toast{position:fixed;top:20px;right:20px;padding:12px 24px;border-radius:10px;color:#fff;font-size:13px;font-weight:500;z-index:9999;opacity:0;transform:translateY(-10px);transition:all .3s;box-shadow:0 8px 24px rgba(0,0,0,.15)}
.toast.show{opacity:1;transform:translateY(0)}
.toast-success{background:#2d8a4e}
.toast-error{background:#cd201f}
.empty{padding:48px;text-align:center;color:#bbb;font-size:14px}
.tab-content{display:none}
.tab-content.active{display:block}
</style>
</head>
<body>
<div class="toast" id="toast"></div>
<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">知</div>
    <span class="topbar-title">知微云</span>
    <span class="topbar-sub">管理平台</span>
  </div>
  <div class="topbar-right">
    <span style="font-size:12px;color:#999">管理会话已认证</span>
    <a href="/admin" class="logout-link">重新登录</a>
  </div>
</div>
<div class="container">
  <div class="stats" id="stats"></div>
  <div class="tabs">
    <div class="tab active" data-tab="licenses" onclick="switchTab('licenses')">License 管理</div>
    <div class="tab" data-tab="deployments" onclick="switchTab('deployments')">部署状态</div>
    <div class="tab" data-tab="alerts" onclick="switchTab('alerts')">告警中心</div>
  </div>

  <div id="tab-licenses" class="tab-content active">
    <div class="panel">
      <div class="panel-title">新建 / 更新 License <small>设置租户授权状态和到期时间</small></div>
      <div class="form-row">
        <div class="form-group"><label>Tenant ID</label><input id="f-tenant" placeholder="如 sch-0001" style="width:170px"></div>
        <div class="form-group"><label>Product</label><select id="f-product" style="width:110px"><option>school</option><option>mfg</option></select></div>
        <div class="form-group"><label>状态</label><select id="f-status" style="width:110px"><option value="active">active</option><option value="trial">trial</option><option value="none">none</option></select></div>
        <div class="form-group"><label>到期时间</label><input id="f-expires" type="datetime-local" style="width:190px"></div>
        <div class="form-group"><button class="btn btn-primary" onclick="saveLicense()" style="margin-top:18px">保存</button></div>
      </div>
      <table><thead><tr><th>Tenant ID</th><th>Product</th><th>状态</th><th>到期时间</th><th>更新于</th><th>操作</th></tr></thead><tbody id="license-tbody"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody></table>
    </div>
  </div>

  <div id="tab-deployments" class="tab-content">
    <div class="panel">
      <table><thead><tr><th>Deployment</th><th>Tenant</th><th>Product</th><th>状态</th><th>版本</th><th>最后心跳</th><th>失联次数</th></tr></thead><tbody id="deploy-tbody"><tr><td colspan="7" class="empty">加载中...</td></tr></tbody></table>
    </div>
  </div>

  <div id="tab-alerts" class="tab-content">
    <div class="panel">
      <div id="alert-list"><div class="empty">加载中...</div></div>
    </div>
  </div>
</div>

<script>
var KEY='""" + api_key + """';
var HEADERS={'X-Api-Key':KEY,'Content-Type':'application/json'};
function $(id){return document.getElementById(id)}
function toast(m,t){var e=$('toast');e.textContent=m;e.className='toast toast-'+t+' show';setTimeout(function(){e.className='toast toast-'+t},3000)}
function switchTab(n){document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active',t.dataset.tab==n)});document.querySelectorAll('.tab-content').forEach(function(t){t.classList.toggle('active',t.id=='tab-'+n)})}
function fd(d){if(!d)return'-';return new Date(d).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}
function badge(s){var m={'active':'badge-active','trial':'badge-trial','none':'badge-none','online':'badge-online','offline':'badge-offline'};return'<span class="badge '+(m[s]||'badge-none')+'">'+s+'</span>'}

async function loadStats(){try{var l=await(await fetch('/api/v1/admin/licenses',{headers:HEADERS})).json();var d=await(await fetch('/api/v1/status',{headers:HEADERS})).json();var a=await(await fetch('/api/v1/alerts',{headers:HEADERS})).json();var ac=0,tr=0,on=0,off=0;l.forEach(function(x){if(x.status=='active')ac++;if(x.status=='trial')tr++});d.forEach(function(x){if(x.status=='online')on++;if(x.status=='offline')off++});$('stats').innerHTML='<div class=\"stat\"><div class=\"stat-label\">活跃 License</div><div class=\"stat-value ok\">'+ac+'</div><div class=\"stat-sub\">正常授权</div></div><div class=\"stat\"><div class=\"stat-label\">试用 License</div><div class=\"stat-value warn\">'+tr+'</div><div class=\"stat-sub\">即将到期</div></div><div class=\"stat\"><div class=\"stat-label\">在线部署</div><div class=\"stat-value ok\">'+on+'</div><div class=\"stat-sub\">运行中</div></div><div class=\"stat\"><div class=\"stat-label\">离线部署</div><div class=\"stat-value danger\">'+off+'</div><div class=\"stat-sub\">需关注</div></div><div class=\"stat\"><div class=\"stat-label\">告警</div><div class=\"stat-value '+(a.count>0?'warn':'ok')+'\">'+a.count+'</div><div class=\"stat-sub\">'+(a.count>0?'待处理':'无')+'</div></div>'}catch(e){}}
async function loadLicenses(){try{var d=await(await fetch('/api/v1/admin/licenses',{headers:HEADERS})).json();if(!d.length){$('license-tbody').innerHTML='<tr><td colspan=\"6\" class=\"empty\">暂无 License 记录</td></tr>';return}$('license-tbody').innerHTML=d.map(function(x){return'<tr><td><code style=\"background:#f5f6fa;padding:2px 6px;border-radius:4px;font-size:12px\">'+x.tenant_id+'</code></td><td>'+x.product+'</td><td>'+badge(x.status)+'</td><td>'+fd(x.expires_at)+'</td><td>'+fd(x.updated_at)+'</td><td><button class=\"btn btn-primary btn-sm\" onclick=\"el(\\''+x.tenant_id+'\\',\\''+x.product+'\\',\\''+x.status+'\\',\\''+(x.expires_at||'')+'\\')\">编辑</button></td></tr>'}).join('')}catch(e){$('license-tbody').innerHTML='<tr><td colspan=\"6\" class=\"empty\">加载失败: '+e.message+'</td></tr>'}}
async function loadDeployments(){try{var d=await(await fetch('/api/v1/status',{headers:HEADERS})).json();if(!d.length){$('deploy-tbody').innerHTML='<tr><td colspan=\"7\" class=\"empty\">暂无部署记录</td></tr>';return}$('deploy-tbody').innerHTML=d.map(function(x){return'<tr><td><code style=\"background:#f5f6fa;padding:2px 6px;border-radius:4px;font-size:12px\">'+x.deployment_id+'</code></td><td>'+x.tenant_id+'</td><td>'+x.product+'</td><td>'+badge(x.status)+'</td><td>'+x.version+'</td><td>'+fd(x.last_heartbeat_at)+'</td><td>'+x.consecutive_misses+'</td></tr>'}).join('')}catch(e){$('deploy-tbody').innerHTML='<tr><td colspan=\"7\" class=\"empty\">加载失败: '+e.message+'</td></tr>'}}
async function loadAlerts(){try{var d=await(await fetch('/api/v1/alerts',{headers:HEADERS})).json();if(!d.alerts.length){$('alert-list').innerHTML='<div class=\"empty\" style=\"color:#2d8a4e\">🎉 当前无告警</div>';return}$('alert-list').innerHTML=d.alerts.map(function(a){var c=a.alert_type=='offline'||a.alert_type=='license_critical'?'critical':a.alert_type=='license_warn'?'warn':'info';return'<div class=\"alert-box '+c+'\"><div class=\"alert-title\">'+a.alert_type.replace('_',' ') +' · '+a.message+'</div><div class=\"alert-detail\">'+(a.detail?JSON.stringify(a.detail):'')+'</div></div>'}).join('')}catch(e){$('alert-list').innerHTML='<div class=\"empty\">加载失败: '+e.message+'</div>'}}
function el(tid,prod,status,expires){$('f-tenant').value=tid;$('f-product').value=prod;$('f-status').value=status;if(expires){var d=new Date(expires);$('f-expires').value=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+'T'+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')}else{$('f-expires').value=''}window.scrollTo({top:0,behavior:'smooth'})}
async function saveLicense(){var tid=$('f-tenant').value.trim(),s=$('f-status').value,ex=$('f-expires').value,p=$('f-product').value;if(!tid){toast('请输入 Tenant ID','error');return}var b={tenant_id:tid,product:p,status:s};if(ex)b.expires_at=new Date(ex).toISOString();try{var r=await fetch('/api/v1/admin/licenses',{method:'POST',headers:HEADERS,body:JSON.stringify(b)});if(!r.ok)throw new Error((await r.json()).detail||r.statusText);toast('License '+tid+' 已更新为 '+s,'success');loadLicenses();loadStats()}catch(e){toast('保存失败: '+e.message,'error')}}
loadStats();loadLicenses();loadDeployments();loadAlerts();
</script>
</body>
</html>"""

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=LOGIN_PAGE if not validated else DASHBOARD_PAGE, status_code=200)


# ============================================================
# Routes — Alerts
# ============================================================


@app.get("/api/v1/alerts")
def list_alerts(
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    List active alerts.

    Returns:
    - Deployments with status="offline"
    - Licenses expiring within the warn/critical window (from License table)
    """
    now = datetime.now(timezone.utc)
    warn_threshold = now + timedelta(days=settings.license_warn_days)
    alerts: list[dict] = []

    # 1) Offline deployments
    offline_deps = (
        db.query(Deployment).filter(Deployment.status == "offline").all()
    )
    for dep in offline_deps:
        alerts.append({
            "deployment_id": dep.deployment_id,
            "tenant_id": dep.tenant_id,
            "product": dep.product,
            "alert_type": "offline",
            "message": (
                f"Deployment {dep.deployment_id} is offline "
                f"({dep.consecutive_misses} missed heartbeats)"
            ),
            "detail": {
                "last_heartbeat_at": (
                    dep.last_heartbeat_at.isoformat()
                    if dep.last_heartbeat_at
                    else None
                ),
                "consecutive_misses": dep.consecutive_misses,
            },
        })

    # 2) License expiry (from License table, active/trial only)
    active_licenses = (
        db.query(License)
        .filter(
            License.expires_at <= warn_threshold,
            License.expires_at > now,
            License.status.in_(["active", "trial"]),
        )
        .all()
    )
    for lic in active_licenses:
        expires_at = lic.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        days_left = (expires_at - now).days
        if days_left <= settings.license_critical_days:
            alert_type = "license_critical"
        else:
            alert_type = "license_warn"

        alerts.append({
            "tenant_id": lic.tenant_id,
            "product": lic.product,
            "alert_type": alert_type,
            "message": (
                f"License for {lic.tenant_id} ({lic.product}) expires "
                f"in {days_left} day(s)"
            ),
            "detail": {
                "expires_at": expires_at.isoformat(),
                "days_left": days_left,
            },
        })

    return {"alerts": alerts, "count": len(alerts)}


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.port)
