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
def admin_page(_api_key: str = Depends(verify_api_key)):
    """License management dashboard (HTML). Requires X-Api-Key header for access."""
    api_key = settings.api_key
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>知微·License 管理</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f6fa;color:#333;padding:24px}}
h1{{font-size:22px;margin-bottom:16px;color:#1a3a6b}}
h2{{font-size:16px;margin:24px 0 12px;color:#333;border-bottom:2px solid #e8ecf1;padding-bottom:6px}}
.stats{{display:flex;gap:16px;margin-bottom:20px}}
.stat{{background:#fff;border-radius:8px;padding:14px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08);flex:1}}
.stat-label{{font-size:12px;color:#888}}
.stat-value{{font-size:24px;font-weight:700;color:#1a3a6b}}
.stat-value.warn{{color:#e6a23c}}
.stat-value.danger{{color:#f56c6c}}
.stat-value.ok{{color:#67c23a}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
th,td{{padding:10px 14px;text-align:left;font-size:13px}}
th{{background:#f0f2f5;font-weight:600;color:#555}}
tr:not(:last-child) td{{border-bottom:1px solid #f0f2f5}}
tr:hover td{{background:#f8f9fc}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}}
.badge-active{{background:#e1f3d8;color:#67c23a}}
.badge-trial{{background:#faecd8;color:#e6a23c}}
.badge-none{{background:#f0f2f5;color:#999}}
.badge-online{{background:#e1f3d8;color:#67c23a}}
.badge-offline{{background:#fde2e2;color:#f56c6c}}
.btn{{display:inline-block;padding:6px 16px;border:none;border-radius:6px;font-size:13px;cursor:pointer;color:#fff}}
.btn-primary{{background:#1a3a6b}}
.btn-primary:hover{{background:#14305a}}
.btn-sm{{padding:4px 10px;font-size:11px}}
.btn-warn{{background:#e6a23c}}
.btn-warn:hover{{background:#cf8e32}}
input,select{{padding:6px 10px;border:1px solid #dcdfe6;border-radius:6px;font-size:13px;outline:0}}
input:focus,select:focus{{border-color:#1a3a6b;box-shadow:0 0 0 2px rgba(26,58,107,.15)}}
.form-row{{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:16px}}
.form-row label{{font-size:12px;color:#666;display:block;margin-bottom:2px}}
.form-group{{display:flex;flex-direction:column}}
.alert-box{{background:#fff;border-radius:8px;padding:14px 18px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.08);border-left:4px solid #e6a23c}}
.alert-box.critical{{border-left-color:#f56c6c}}
.alert-box.info{{border-left-color:#409eff}}
.alert-title{{font-weight:600;font-size:13px}}
.alert-detail{{font-size:12px;color:#888;margin-top:4px}}
.toast{{position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:8px;color:#fff;font-size:13px;z-index:999;opacity:0;transition:opacity .3s}}
.toast.show{{opacity:1}}
.toast-success{{background:#67c23a}}
.toast-error{{background:#f56c6c}}
.empty{{padding:40px;text-align:center;color:#999;font-size:14px}}
.tabs{{display:flex;gap:0;margin-bottom:16px}}
.tab{{padding:8px 20px;cursor:pointer;border-bottom:2px solid transparent;font-size:14px;color:#666;transition:all .2s}}
.tab.active{{border-bottom-color:#1a3a6b;color:#1a3a6b;font-weight:600}}
.tab:hover{{color:#1a3a6b}}
.tab-content{{display:none}}
.tab-content.active{{display:block}}
</style>
</head>
<body>
<div class="toast" id="toast"></div>

<h1>🔑 知微 · License 管理</h1>
<div class="stats" id="stats"></div>

<div class="tabs">
  <div class="tab active" data-tab="licenses" onclick="switchTab('licenses')">License 列表</div>
  <div class="tab" data-tab="deployments" onclick="switchTab('deployments')">部署状态</div>
  <div class="tab" data-tab="alerts" onclick="switchTab('alerts')">告警</div>
</div>

<div id="tab-licenses" class="tab-content active">
  <h2>新建 / 更新 License</h2>
  <div class="form-row">
    <div class="form-group"><label>Tenant ID</label><input id="f-tenant" placeholder="如 sch-0001" style="width:180px"></div>
    <div class="form-group"><label>Product</label><select id="f-product"><option>school</option><option>mfg</option></select></div>
    <div class="form-group"><label>状态</label><select id="f-status"><option value="active">active</option><option value="trial">trial</option><option value="none">none</option></select></div>
    <div class="form-group"><label>到期时间</label><input id="f-expires" type="datetime-local" style="width:200px"></div>
    <div><button class="btn btn-primary" onclick="saveLicense()">保存</button></div>
  </div>
  <table><thead><tr><th>Tenant</th><th>Product</th><th>状态</th><th>到期时间</th><th>更新时间</th><th>操作</th></tr></thead><tbody id="license-tbody"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody></table>
</div>

<div id="tab-deployments" class="tab-content">
  <table><thead><tr><th>Deployment ID</th><th>Tenant</th><th>Product</th><th>状态</th><th>版本</th><th>最后心跳</th><th>连续失败</th></tr></thead><tbody id="deploy-tbody"><tr><td colspan="7" class="empty">加载中...</td></tr></tbody></table>
</div>

<div id="tab-alerts" class="tab-content">
  <div id="alert-list"><div class="empty">加载中...</div></div>
</div>

<script>
const KEY='{api_key}';
const HEADERS={{'X-Api-Key':KEY,'Content-Type':'application/json'}};
function $(id){{return document.getElementById(id)}}
function toast(msg,type){{var t=$('toast');t.textContent=msg;t.className='toast toast-'+type+' show';setTimeout(function(){{t.className='toast toast-'+type}},3000)}}
function switchTab(name){{document.querySelectorAll('.tab').forEach(function(t){{t.classList.toggle('active',t.dataset.tab==name)}});document.querySelectorAll('.tab-content').forEach(function(t){{t.classList.toggle('active',t.id=='tab-'+name)}})}}
function fmtDate(d){{if(!d)return'-';return new Date(d).toLocaleString('zh-CN',{{timeZone:'Asia/Shanghai'}})}}
function badge(status){{var m={{'active':'badge-active','trial':'badge-trial','none':'badge-none','online':'badge-online','offline':'badge-offline'}};return'<span class="badge '+(m[status]||'badge-none')+'">'+status+'</span>'}}

async function loadStats(){{
  try{{
    var l=await(await fetch('/api/v1/admin/licenses',{{headers:HEADERS}})).json();
    var d=await(await fetch('/api/v1/status',{{headers:HEADERS}})).json();
    var a=await(await fetch('/api/v1/alerts',{{headers:HEADERS}})).json();
    var active=0,trial=0,online=0,offline=0;
    l.forEach(function(x){{if(x.status=='active')active++;if(x.status=='trial')trial++}});
    d.forEach(function(x){{if(x.status=='online')online++;if(x.status=='offline')offline++}});
    $('stats').innerHTML='<div class="stat"><div class="stat-label">活跃 License</div><div class="stat-value ok">'+active+'</div></div><div class="stat"><div class="stat-label">试用 License</div><div class="stat-value warn">'+trial+'</div></div><div class="stat"><div class="stat-label">在线部署</div><div class="stat-value ok">'+online+'</div></div><div class="stat"><div class="stat-label">离线部署</div><div class="stat-value danger">'+offline+'</div></div><div class="stat"><div class="stat-label">告警</div><div class="stat-value '+(a.count>0?'warn':'ok')+'">'+a.count+'</div></div>';
  }}catch(e){{}}
}}

async function loadLicenses(){{
  try{{
    var data=await(await fetch('/api/v1/admin/licenses',{{headers:HEADERS}})).json();
    if(!data.length){{$('license-tbody').innerHTML='<tr><td colspan="6" class="empty">暂无 License 记录</td></tr>';return}}
    $('license-tbody').innerHTML=data.map(function(x){{return'<tr><td>'+x.tenant_id+'</td><td>'+x.product+'</td><td>'+badge(x.status)+'</td><td>'+fmtDate(x.expires_at)+'</td><td>'+fmtDate(x.updated_at)+'</td><td><button class="btn btn-primary btn-sm" onclick="editLicense(\\''+x.tenant_id+'\\',\\''+x.product+'\\',\\''+x.status+'\\',\\''+(x.expires_at||'')+'\\')">编辑</button></td></tr>'}}).join('');
  }}catch(e){{$('license-tbody').innerHTML='<tr><td colspan="6" class="empty">加载失败: '+e.message+'</td></tr>'}}
}}

async function loadDeployments(){{
  try{{
    var data=await(await fetch('/api/v1/status',{{headers:HEADERS}})).json();
    if(!data.length){{$('deploy-tbody').innerHTML='<tr><td colspan="7" class="empty">暂无部署记录</td></tr>';return}}
    $('deploy-tbody').innerHTML=data.map(function(x){{return'<tr><td>'+x.deployment_id+'</td><td>'+x.tenant_id+'</td><td>'+x.product+'</td><td>'+badge(x.status)+'</td><td>'+x.version+'</td><td>'+fmtDate(x.last_heartbeat_at)+'</td><td>'+x.consecutive_misses+'</td></tr>'}}).join('');
  }}catch(e){{$('deploy-tbody').innerHTML='<tr><td colspan="7" class="empty">加载失败: '+e.message+'</td></tr>'}}
}}

async function loadAlerts(){{
  try{{
    var data=await(await fetch('/api/v1/alerts',{{headers:HEADERS}})).json();
    if(!data.alerts.length){{$('alert-list').innerHTML='<div class="empty">🎉 无告警</div>';return}}
    $('alert-list').innerHTML=data.alerts.map(function(a){{var cls=a.alert_type=='offline'?'critical':a.alert_type=='license_critical'?'critical':a.alert_type=='license_warn'?'warn':'info';return'<div class="alert-box '+cls+'"><div class="alert-title">'+a.alert_type+' · '+a.message+'</div><div class="alert-detail">'+(a.detail?JSON.stringify(a.detail):'')+'</div></div>'}}).join('');
  }}catch(e){{$('alert-list').innerHTML='<div class="empty">加载失败: '+e.message+'</div>'}}
}}

function editLicense(tid,prod,status,expires){{
  $('f-tenant').value=tid;$('f-product').value=prod;$('f-status').value=status;
  if(expires){{var d=new Date(expires);$('f-expires').value=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+'T'+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')}}else{{$('f-expires').value=''}}
  window.scrollTo({{top:0,behavior:'smooth'}})
}}

async function saveLicense(){{
  var tid=$('f-tenant').value.trim(),status=$('f-status').value,expires=$('f-expires').value,prod=$('f-product').value;
  if(!tid){{toast('请输入 Tenant ID','error');return}}
  var body={{tenant_id:tid,product:prod,status:status}};
  if(expires)body.expires_at=new Date(expires).toISOString();
  try{{
    var r=await fetch('/api/v1/admin/licenses',{{method:'POST',headers:HEADERS,body:JSON.stringify(body)}});
    if(!r.ok)throw new Error((await r.json()).detail||r.statusText);
    toast('License '+tid+' 已更新为 '+status,'success');
    loadLicenses();loadStats()
  }}catch(e){{toast('保存失败: '+e.message,'error')}}
}}

loadStats();loadLicenses();loadDeployments();loadAlerts();
</script>
</body>
</html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html, status_code=200)


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
