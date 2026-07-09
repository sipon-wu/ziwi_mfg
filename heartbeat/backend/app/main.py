"""
Heartbeat Service — Ziwi License Heartbeat Monitor.

Receives periodic heartbeats from on-premises deployment instances,
monitors online status, and provides license expiry alerts.

Single-file FastAPI application incorporating config, models,
dependencies, routes, and APScheduler background tasks.
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
# Model
# ============================================================


class Deployment(Base):
    """Represents a registered on-premises deployment instance."""

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


# ============================================================
# Pydantic Schemas
# ============================================================


class HeartbeatRequest(BaseModel):
    """Payload sent by a deployment instance on each heartbeat."""

    deployment_id: str = Field(..., max_length=64, description="Unique deployment identifier")
    tenant_id: str = Field(..., max_length=64, description="Owning tenant ID")
    product: str = Field(..., max_length=32, description="Product: mfg or school")
    version: str = Field(default="", max_length=32, description="Software version")
    license_issued_at: Optional[datetime] = Field(
        default=None, description="License issue date (required for new deployments)"
    )
    license_expires_at: Optional[datetime] = Field(
        default=None, description="License expiry date (required for new deployments)"
    )


class HeartbeatResponse(BaseModel):
    """Response returned after a heartbeat is processed."""

    status: str
    deployment_id: str


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
    version="1.0.0",
    lifespan=lifespan,
)

# ============================================================
# Routes
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

    - If deployment_id is new, auto-creates the Deployment record
      (requires license_issued_at & license_expires_at in payload).
    - If deployment_id exists, updates last_heartbeat_at, resets
      consecutive_misses to 0, and sets status=online.
    """
    now = datetime.now(timezone.utc)
    dep = (
        db.query(Deployment)
        .filter(Deployment.deployment_id == req.deployment_id)
        .first()
    )

    if dep is None:
        # --- create new deployment ---
        if req.license_issued_at is None or req.license_expires_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "New deployment requires license_issued_at "
                    "and license_expires_at"
                ),
            )
        dep = Deployment(
            deployment_id=req.deployment_id,
            tenant_id=req.tenant_id,
            product=req.product,
            version=req.version,
            license_issued_at=req.license_issued_at,
            license_expires_at=req.license_expires_at,
            last_heartbeat_at=now,
            status="online",
            consecutive_misses=0,
        )
        db.add(dep)
        db.commit()
        db.refresh(dep)
        logger.info("New deployment registered: %s", req.deployment_id)
        return HeartbeatResponse(status="created", deployment_id=dep.deployment_id)

    # --- update existing deployment ---
    dep.last_heartbeat_at = now
    dep.consecutive_misses = 0
    dep.status = "online"
    dep.version = req.version or dep.version
    dep.tenant_id = req.tenant_id or dep.tenant_id
    dep.product = req.product or dep.product
    dep.updated_at = now
    db.commit()
    return HeartbeatResponse(status="updated", deployment_id=dep.deployment_id)


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


@app.get("/api/v1/alerts")
def list_alerts(
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    List active alerts.

    Returns:
    - Deployments with status="offline"
    - Deployments whose license expires within the warn/critical window
      (but are still online, to avoid duplicates)
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

    # 2) License expiry (online deployments only, to avoid noise)
    expiring_deps = (
        db.query(Deployment)
        .filter(
            Deployment.license_expires_at <= warn_threshold,
            Deployment.license_expires_at > now,
            Deployment.status == "online",
        )
        .all()
    )

    for dep in expiring_deps:
        # SQLite stores naive datetimes; make them comparable with timezone-aware now
        expires_at = dep.license_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        days_left = (expires_at - now).days
        if days_left <= settings.license_critical_days:
            alert_type = "license_critical"
        else:
            alert_type = "license_warn"

        alerts.append({
            "deployment_id": dep.deployment_id,
            "tenant_id": dep.tenant_id,
            "product": dep.product,
            "alert_type": alert_type,
            "message": (
                f"License for {dep.deployment_id} expires "
                f"in {days_left} day(s)"
            ),
            "detail": {
                "license_expires_at": dep.license_expires_at.isoformat(),
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
