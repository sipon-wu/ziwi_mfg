"""
Heartbeat Service — License & Deployment Monitoring Platform.

Multi-role RBAC platform:
  * Composable assignment: a user holds a set of ROLES + directly-granted
    extra PERMISSIONS; effective permissions = union(roles) + extras.
  * Fail-closed enforcement: missing permission => 403; missing auth => 401.
  * Signed session cookie (no server-side state) => survives restart / replica.
  * All account & permission changes are written to admin_audit (non-repudiation).
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Optional

import logging

logger = logging.getLogger("heartbeat")

import base64
import hashlib
import hmac
import json
import time
import uuid

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from .config import settings
from .models import (
    AdminAudit,
    AdminUser,
    Customer,
    ALL_PERMISSIONS,
    Base,
    Deployment,
    License,
    LicenseAudit,
    LoginAttempt,
    NAV_ITEMS,
    PERM_ALERTS,
    PERM_AUDIT,
    PERM_CUSTOMERS,
    PERM_DASHBOARD,
    PERM_DEPLOYMENTS,
    PERM_LICENSE_MANAGE,
    PERM_LICENSE_VIEW,
    PERM_LABELS,
    PERM_SETTINGS,
    PERM_USERS,
    ROLE_LABELS,
    ROLE_OPS,
    ROLE_PERMISSIONS,
    ROLE_SUPER_ADMIN,
    get_effective_permissions,
    hash_password,
    init_db,
    verify_password,
)

# ---------------------------------------------------------------------------
# Session (signed cookie — no in-memory state => reliable across restart/replica)
# ---------------------------------------------------------------------------

MAX_AGE_SECONDS = 8 * 3600
COOKIE_NAME = "hb_session"


def _aware(dt):
    """Coerce a possibly-naive datetime (as stored by SQLite) to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _session_secret_bytes() -> bytes:
    return (settings.session_secret or settings.admin_password or "changeme").encode()


def _b64e(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _b64d(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad).decode()


def _sign_session(payload: dict) -> str:
    body = _b64e(json.dumps(payload))
    sig = hmac.new(_session_secret_bytes(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify_signed(token: str) -> Optional[dict]:
    try:
        body, sig = token.rsplit(".", 1)
        expected = hmac.new(_session_secret_bytes(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(_b64d(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _auth_from_user(user) -> dict:
    return {
        "uid": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "roles": [r for r in (getattr(user, "roles", None) or user.role or "").split(",") if r.strip()],
        "permissions": get_effective_permissions(user),
    }


def _get_session(request: Request) -> Optional[dict]:
    """Resolve the live operator identity from the signed cookie.

    Loads the user every request so permission/role changes take effect
    immediately (no stale session). Returns None when unauthenticated/expired.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = _verify_signed(token)
    if not payload:
        return None
    uid = payload.get("uid")
    if uid is None:
        return None
    db = SessionLocal()
    try:
        user = db.get(AdminUser, uid)
        if user is None or not user.is_active:
            return None
        return _auth_from_user(user)
    finally:
        db.close()





def require_perm(perm: str):
    """Dependency factory: fail-closed permission check (403 when missing)."""

    def _checker(request: Request) -> dict:
        sess = _get_session(request)
        if not sess:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if perm not in sess["permissions"]:
            raise HTTPException(status_code=403, detail="Permission denied")
        return sess

    return _checker


def _filtered_nav(permissions: list) -> list:
    items = []
    for item in NAV_ITEMS:
        if item.get("placeholder"):
            items.append(item)
            continue
        perm = item.get("perm")
        if perm and perm in permissions:
            items.append(item)
    return items


def _render_admin_page(request, template, require: Optional[str] = None, **extra):
    """Render an admin page, enforcing authentication + page-level permission."""
    sess = _get_session(request)
    if not sess:
        return RedirectResponse(url="/admin/login", status_code=303)
    if require is not None and require not in sess["permissions"]:
        return RedirectResponse(url="/admin", status_code=303)
    role_labels = [ROLE_LABELS.get(r, r) for r in sess["roles"]]
    ctx = {
        "request": request,
        "roles": sess["roles"],
        "role_labels": role_labels,
        "role_label": " / ".join(role_labels) or "—",
        "username": sess["username"],
        "display_name": sess["display_name"],
        "permissions": sess["permissions"],
        "nav_items": _filtered_nav(sess["permissions"]),
    }
    ctx.update(extra)
    return templates.TemplateResponse(request, template, ctx)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# RBAC catalogs (for the user-management UI)
# ---------------------------------------------------------------------------

ROLES_CATALOG = [{"key": k, "label": ROLE_LABELS.get(k, k)} for k in ROLE_PERMISSIONS]
PERMS_CATALOG = [{"key": p, "label": PERM_LABELS.get(p, p)} for p in ALL_PERMISSIONS]


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def _record_audit(
    db: Session,
    actor: str,
    tenant_id: str,
    product: str,
    action: str,
    old_status: Optional[str],
    new_status: Optional[str],
    ip: Optional[str] = None,
):
    rec = LicenseAudit(
        tenant_id=tenant_id,
        product=product,
        action=action,
        old_status=old_status,
        new_status=new_status,
        changed_by=actor,
        ip_address=ip,
    )
    db.add(rec)
    db.commit()


def _record_admin_audit(
    db: Session,
    actor: str,
    action: str,
    target: str,
    old_roles: Optional[str] = None,
    new_roles: Optional[str] = None,
    old_perms: Optional[str] = None,
    new_perms: Optional[str] = None,
    ip: Optional[str] = None,
):
    rec = AdminAudit(
        actor=actor,
        action=action,
        target_user=target,
        old_roles=old_roles,
        new_roles=new_roles,
        old_perms=old_perms,
        new_perms=new_perms,
        ip_address=ip,
    )
    db.add(rec)
    db.commit()


# ---------------------------------------------------------------------------
# Brute-force protection
# ---------------------------------------------------------------------------

def _record_attempt(ip: str, success: bool):
    db = SessionLocal()
    try:
        db.add(LoginAttempt(ip_address=ip, success=success))
        db.commit()
    finally:
        db.close()


def _is_locked(ip: str) -> bool:
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc).timestamp() - settings.login_lockout_minutes * 60
        since_dt = datetime.fromtimestamp(since, tz=timezone.utc)
        recent = (
            db.query(LoginAttempt)
            .filter(LoginAttempt.ip_address == ip, LoginAttempt.attempted_at >= since_dt)
            .all()
        )
        failures = [a for a in recent if not a.success and _aware(a.attempted_at) >= since_dt]
        return len(failures) >= settings.login_max_attempts
    finally:
        db.close()


# ---------------------------------------------------------------------------
# License helpers
# ---------------------------------------------------------------------------

def _lookup_license(db: Session, tenant_id: str, product: str) -> Optional[License]:
    return (
        db.query(License)
        .filter(License.tenant_id == tenant_id, License.product == product)
        .first()
    )


# ---------------------------------------------------------------------------
# Customers / Deployments views
# ---------------------------------------------------------------------------

def _get_customers_view(db: Session) -> list:
    licenses = db.query(License).all()
    deployments = db.query(Deployment).all()
    by_tenant: dict[str, dict] = {}

    for lic in licenses:
        c = by_tenant.setdefault(lic.tenant_id, {
            "tenant_id": lic.tenant_id, "status": "none",
            "products": [], "expires_at": None, "deployments": 0, "online": 0,
        })
        c["products"].append({"product": lic.product, "status": lic.status, "expires_at": lic.expires_at})
        order = {"active": 3, "trial": 2, "none": 1, "expired": 0}
        if order.get(lic.status, 0) > order.get(c["status"], 0):
            c["status"] = lic.status
        if lic.expires_at and (c["expires_at"] is None or lic.expires_at > c["expires_at"]):
            c["expires_at"] = lic.expires_at

    for dep in deployments:
        c = by_tenant.setdefault(dep.tenant_id, {
            "tenant_id": dep.tenant_id, "status": "none",
            "products": [], "expires_at": None, "deployments": 0, "online": 0,
        })
        c["deployments"] += 1
        if dep.last_heartbeat_at and (datetime.now(timezone.utc) - _aware(dep.last_heartbeat_at)).total_seconds() < settings.heartbeat_timeout_minutes * 60:
            c["online"] += 1
    return list(by_tenant.values())


def _enrich_customer(db: Session, c: Customer) -> dict:
    """Attach runtime-derived stats (licenses/deployments) to a Customer master row."""
    d = c.to_dict()
    lic = db.query(License).filter_by(tenant_id=c.tenant_id).all()
    deps = db.query(Deployment).filter_by(tenant_id=c.tenant_id).all()
    order = {"active": 3, "trial": 2, "none": 1, "expired": 0}
    agg = "none"
    for l in lic:
        if order.get(l.status, 0) > order.get(agg, 0):
            agg = l.status
    expires = [l.expires_at for l in lic if l.expires_at]
    min_exp = min(expires) if expires else None
    hbs = [dp.last_heartbeat_at for dp in deps if dp.last_heartbeat_at]
    last = max(hbs) if hbs else None
    days_left = (min_exp - datetime.now(timezone.utc)).days if min_exp else None
    d["derived"] = {
        "products": [l.product for l in lic],
        "license_status": agg,
        "deployment_count": len(deps),
        "last_heartbeat_at": last.isoformat() if last else None,
        "days_left": days_left,
    }
    return d


def check_deployments():
    db = SessionLocal()
    try:
        timeout = settings.heartbeat_timeout_minutes * 60
        cutoff = time.time() - timeout
        deps = db.query(Deployment).all()
        for dep in deps:
            online = bool(dep.last_heartbeat_at) and _aware(dep.last_heartbeat_at).timestamp() >= cutoff
            new_misses = 0 if online else dep.consecutive_misses + 1
            new_status = "online" if online else "offline"
            if dep.status != new_status or dep.consecutive_misses != new_misses:
                dep.status = new_status
                dep.consecutive_misses = new_misses
        db.commit()
    finally:
        db.close()


# ===========================================================================
# App setup
# ===========================================================================

templates = Jinja2Templates(directory="app/templates")
engine, SessionLocal = init_db(settings.database_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    if not settings.session_secret:
        logger.warning(
            "HEARTBEAT_SESSION_SECRET 未设置，会话签名回退到 admin_password；"
            "生产环境请设置强随机密钥以防会话被伪造。"
        )
    if not settings.admin_cookie_secure:
        logger.warning(
            "HEARTBEAT_ADMIN_SECURE_COOKIE 为 false，会话 cookie 未启用 Secure 属性；"
            "HTTPS 部署环境请设为 true，避免 cookie 经明文通道泄露。"
        )
    # --- schema migrations for existing tables (SQLite: add missing columns) ---
    migrations = {
        "admin_users": [("roles", "VARCHAR(255)"), ("extra_permissions", "TEXT")],
        "licenses": [("last_seen", "DATETIME"), ("last_version", "VARCHAR(32)"), ("heartbeats", "INTEGER"), ("licensee", "VARCHAR(128)"), ("seats", "INTEGER"), ("notes", "TEXT")],
        "license_audit": [("product", "VARCHAR(32)")],
    }
    with engine.begin() as conn:
        for table, cols in migrations.items():
            present = {c["name"] for c in inspect(engine).get_columns(table)}
            for col, ctype in cols:
                if col not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}"))
                    logger.info("Migrated: added column %s.%s", table, col)
    _migrate_license_composite_unique(engine)
    # Backfill composable `roles` column for legacy single-role rows
    db = SessionLocal()
    try:
        for u in db.query(AdminUser).all():
            if not u.roles:
                u.roles = u.role or ROLE_OPS
        db.commit()
    finally:
        db.close()
    init_super_admin()
    import asyncio
    async def _tick():
        while True:
            try:
                check_deployments()
            except Exception:  # 单轮异常不应终止后台巡检
                logger.exception("check_deployments tick failed")
            await asyncio.sleep(settings.check_interval_minutes * 60)
    task = asyncio.create_task(_tick())
    yield
    task.cancel()


app = FastAPI(title="ZiWi Heartbeat Platform", lifespan=lifespan)


def _migrate_license_composite_unique(engine):
    """Rebuild `licenses` to enforce composite UNIQUE (tenant_id, product).

    The legacy schema had a single-column UNIQUE on tenant_id, which prevented a
    tenant from holding more than one product (e.g. mfg + school in parallel) —
    the second heartbeat raised a uniqueness violation and 500'd. SQLite cannot
    ALTER DROP CONSTRAINT, so we rebuild via rename + copy. Idempotent: a no-op
    once the composite unique is already in place (fresh DB or already migrated).
    """
    from sqlalchemy import inspect as _sa_inspect

    insp = _sa_inspect(engine)
    if "licenses" not in insp.get_table_names():
        return  # fresh DB: create_all already applied the composite unique
    idxs = insp.get_indexes("licenses")
    has_old = any(
        ix.get("unique") and ix["column_names"] == ["tenant_id"] for ix in idxs
    )
    has_new = any(
        ix.get("unique")
        and set(ix["column_names"]) == {"tenant_id", "product"}
        for ix in idxs
    )
    if not has_old and has_new:
        return  # already migrated

    cols = [c.name for c in License.__table__.columns]
    col_list = ", ".join(cols)
    create_sql = str(CreateTable(License.__table__)).replace(
        "CREATE TABLE licenses", "CREATE TABLE licenses_new", 1
    )
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("DROP TABLE IF EXISTS licenses_new"))
        conn.execute(text(create_sql))
        conn.execute(
            text(
                f"INSERT INTO licenses_new ({col_list}) "
                f"SELECT {col_list} FROM licenses"
            )
        )
        conn.execute(text("DROP TABLE licenses"))
        conn.execute(text("ALTER TABLE licenses_new RENAME TO licenses"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
    logger.info(
        "Migrated: licenses rebuilt with composite UNIQUE (tenant_id, product)"
    )


def init_super_admin():
    db = SessionLocal()
    try:
        if db.query(AdminUser).count() == 0:
            admin = AdminUser(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                display_name="超级管理员",
                role=ROLE_SUPER_ADMIN,
                roles=ROLE_SUPER_ADMIN,
                extra_permissions="",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            logger.info("Initialized super admin user '%s'", settings.admin_username)
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===========================================================================
# Machine heartbeat (uses machine api_key, NOT admin credentials)
# ===========================================================================

class HeartbeatRequest(BaseModel):
    tenant_id: str
    product: str
    version: Optional[str] = None
    status: Optional[str] = None
    license_status: Optional[str] = None
    license_expires_at: Optional[datetime] = None
    details: Optional[dict] = None


class HeartbeatResponse(BaseModel):
    status: str
    license_status: Optional[str] = None


def verify_api_key(x_api_key: Annotated[Optional[str], Header(alias="X-Api-Key")] = None) -> str:
    if x_api_key and x_api_key == settings.api_key:
        return x_api_key
    raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/heartbeat", response_model=HeartbeatResponse)
def heartbeat_post(req: HeartbeatRequest, _key: str = Depends(verify_api_key)):
    db = SessionLocal()
    try:
        lic = _lookup_license(db, req.tenant_id, req.product)
        if lic is None:
            # Never trust client-reported license_status. Auto-seed as 'none'
            # and require an admin to activate it.
            lic = License(tenant_id=req.tenant_id, product=req.product, status="none")
            db.add(lic)
            db.commit()
            db.refresh(lic)
            logger.info("License auto-seeded tenant=%s product=%s (status=none)", req.tenant_id, req.product)
        lic.last_seen = datetime.now(timezone.utc)
        lic.last_version = req.version
        if lic.heartbeats is None:
            lic.heartbeats = 0
        lic.heartbeats += 1

        dep = (
            db.query(Deployment)
            .filter(Deployment.tenant_id == req.tenant_id, Deployment.product == req.product)
            .first()
        )
        now = datetime.now(timezone.utc)
        if dep is None:
            dep = Deployment(
                deployment_id=uuid.uuid4().hex,
                tenant_id=req.tenant_id,
                product=req.product,
                version=req.version or "",
                license_issued_at=now,
                license_expires_at=lic.expires_at or now,
                last_heartbeat_at=now,
                status="online",
                consecutive_misses=0,
            )
            db.add(dep)
        else:
            dep.last_heartbeat_at = now
            dep.status = "online"
            dep.consecutive_misses = 0
            if req.version:
                dep.version = req.version
        db.commit()
        return HeartbeatResponse(status="ok", license_status=lic.status)
    finally:
        db.close()


# ===========================================================================
# Auth pages
# ===========================================================================

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    sess = _get_session(request)
    if sess:
        return RedirectResponse(url="/admin", status_code=303)
    error = request.query_params.get("error") == "1"
    locked = request.query_params.get("locked") == "1"
    return templates.TemplateResponse(request, "login.html", {
        "error": error, "locked": locked,
        "lockout_minutes": settings.login_lockout_minutes,
    })


@app.post("/admin/login")
def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    if _is_locked(ip):
        return RedirectResponse(url="/admin/login?locked=1", status_code=303)
    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        _record_attempt(ip, success=False)
        return RedirectResponse(url="/admin/login?error=1", status_code=303)
    _record_attempt(ip, success=True)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    payload = {"uid": user.id, "uname": user.username, "exp": int(time.time()) + MAX_AGE_SECONDS}
    token = _sign_session(payload)
    resp = RedirectResponse(url="/admin", status_code=303)
    resp.set_cookie(
        COOKIE_NAME, token, max_age=MAX_AGE_SECONDS,
        httponly=True, secure=settings.admin_cookie_secure, samesite="lax",
    )
    return resp


@app.post("/admin/logout")
def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ===========================================================================
# Admin pages (page-level permission isolation)
# ===========================================================================

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    sess = _get_session(request)
    if not sess:
        return RedirectResponse(url="/admin/login", status_code=303)
    if PERM_DASHBOARD not in sess["permissions"]:
        # 已登录但无 dashboard 权限：跳到第一个有权限的页面，避免退回登录页
        for item in _filtered_nav(sess["permissions"]):
            if item.get("path"):
                return RedirectResponse(url=item["path"], status_code=303)
        return RedirectResponse(url="/admin/login", status_code=303)
    db = SessionLocal()
    try:
        total = db.query(License).count()
        active = db.query(License).filter(License.status == "active").count()
        trial = db.query(License).filter(License.status == "trial").count()
        total_dep = db.query(Deployment).count()
        online = db.query(Deployment).filter(Deployment.status == "online").count()
        alert_count = db.query(Deployment).filter(Deployment.status == "offline").count()
        recent_audit = [a.to_dict() for a in db.query(LicenseAudit).order_by(LicenseAudit.id.desc()).limit(8).all()]
    finally:
        db.close()
    role_labels = [ROLE_LABELS.get(r, r) for r in sess["roles"]]
    return templates.TemplateResponse(request, "dashboard.html", {
        "roles": sess["roles"], "role_labels": role_labels,
        "role_label": " / ".join(role_labels) or "—",
        "username": sess["username"], "display_name": sess["display_name"],
        "permissions": sess["permissions"],
        "nav_items": _filtered_nav(sess["permissions"]),
        "total_licenses": total, "active_licenses": active, "trial_licenses": trial,
        "total_deployments": total_dep, "online_deployments": online,
        "offline_deployments": alert_count, "alert_count": alert_count,
        "recent_audit": recent_audit,
    })


@app.get("/admin/licenses", response_class=HTMLResponse)
def admin_licenses_page(request: Request):
    return _render_admin_page(request, "licenses.html", require=PERM_LICENSE_VIEW)


@app.get("/admin/customers", response_class=HTMLResponse)
def admin_customers_page(request: Request):
    db = SessionLocal()
    try:
        customers = _get_customers_view(db)
    finally:
        db.close()
    return _render_admin_page(request, "customers.html", require=PERM_CUSTOMERS, customers=customers)


class CustomerCreate(BaseModel):
    tenant_id: str
    name: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contract_no: Optional[str] = None
    contract_start: Optional[datetime] = None
    contract_end: Optional[datetime] = None
    region: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class CustomerUpdate(BaseModel):
    """Update customer — all fields optional."""

    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contract_no: Optional[str] = None
    contract_start: Optional[datetime] = None
    contract_end: Optional[datetime] = None
    region: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


@app.get("/api/v1/admin/customers")
def list_customers(
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_perm(PERM_CUSTOMERS)),
):
    """List customer master records enriched with runtime-derived stats, plus
    tenants seen via heartbeats/licenses but not yet filed as a customer."""
    rows = db.query(Customer).order_by(Customer.name).all()
    mapped = {r.tenant_id for r in rows}
    result = [_enrich_customer(db, r) for r in rows]
    tenant_set = {l.tenant_id for l in db.query(License.tenant_id).all()}
    tenant_set |= {d.tenant_id for d in db.query(Deployment.tenant_id).all()}
    unmapped = sorted(tenant_set - mapped)
    return {"customers": result, "unmapped": unmapped}


@app.post("/api/v1/admin/customers")
def create_customer(
    body: CustomerCreate,
    request: Request,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_perm(PERM_CUSTOMERS)),
):
    if db.query(Customer).filter_by(tenant_id=body.tenant_id).first():
        raise HTTPException(409, "该租户已建档")
    c = Customer(
        tenant_id=body.tenant_id,
        name=body.name,
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        contact_email=body.contact_email,
        contract_no=body.contract_no,
        contract_start=body.contract_start,
        contract_end=body.contract_end,
        region=body.region,
        is_active=body.is_active,
        notes=body.notes,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    _record_audit(
        db, _auth["username"], body.tenant_id, None, "customer.create",
        None, c.name, ip=_client_ip(request),
    )
    return c.to_dict()


@app.put("/api/v1/admin/customers/{cid}")
def update_customer(
    cid: int,
    body: CustomerUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_perm(PERM_CUSTOMERS)),
):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    old_name = c.name
    for f in (
        "name", "contact_name", "contact_phone", "contact_email",
        "contract_no", "contract_start", "contract_end", "region",
        "is_active", "notes",
    ):
        val = getattr(body, f, None)
        if val is not None:
            setattr(c, f, val)
    db.commit()
    db.refresh(c)
    _record_audit(
        db, _auth["username"], c.tenant_id, None, "customer.update",
        old_name, c.name, ip=_client_ip(request),
    )
    return c.to_dict()


@app.delete("/api/v1/admin/customers/{cid}")
def delete_customer(
    cid: int,
    request: Request,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_perm(PERM_CUSTOMERS)),
):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    name = c.name
    db.delete(c)
    db.commit()
    _record_audit(
        db, _auth["username"], c.tenant_id, None, "customer.delete",
        name, None, ip=_client_ip(request),
    )
    return {"status": "ok"}


@app.get("/admin/deployments", response_class=HTMLResponse)
def admin_deployments_page(request: Request):
    return _render_admin_page(request, "deployments.html", require=PERM_DEPLOYMENTS)


@app.get("/admin/alerts", response_class=HTMLResponse)
def admin_alerts_page(request: Request):
    return _render_admin_page(request, "alerts.html", require=PERM_ALERTS)


@app.get("/admin/audit", response_class=HTMLResponse)
def admin_audit_page(request: Request):
    return _render_admin_page(request, "audit.html", require=PERM_AUDIT)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    return _render_admin_page(
        request, "users.html", require=PERM_USERS,
        roles_catalog=ROLES_CATALOG, perms_catalog=PERMS_CATALOG,
        role_perm_map=ROLE_PERMISSIONS, perm_labels=PERM_LABELS,
    )


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request):
    return _render_admin_page(request, "settings.html", require=PERM_SETTINGS)


@app.get("/admin/support", response_class=HTMLResponse)
def admin_support_page(request: Request):
    # Reserved placeholder page — visible to all authenticated users, but no
    # real capability is exposed unless a role is granted later.
    return _render_admin_page(request, "support.html")


# ===========================================================================
# License API
# ===========================================================================

class LicenseCreate(BaseModel):
    tenant_id: str
    product: str
    status: str = "none"
    expires_at: Optional[datetime] = None
    licensee: Optional[str] = None
    seats: Optional[int] = None
    notes: Optional[str] = None


@app.get("/api/v1/admin/licenses")
def list_licenses(db: Session = Depends(get_db), _auth: dict = Depends(require_perm(PERM_LICENSE_VIEW))):
    rows = db.query(License).order_by(License.tenant_id).all()
    return [r.to_dict() for r in rows]


@app.post("/api/v1/admin/licenses")
def create_license(body: LicenseCreate, request: Request, db: Session = Depends(get_db),
                   _auth: dict = Depends(require_perm(PERM_LICENSE_MANAGE))):
    if _lookup_license(db, body.tenant_id, body.product):
        raise HTTPException(409, "License already exists for tenant+product")
    lic = License(
        tenant_id=body.tenant_id, product=body.product, status=body.status,
        expires_at=body.expires_at, licensee=body.licensee, seats=body.seats, notes=body.notes,
    )
    db.add(lic)
    db.commit()
    db.refresh(lic)
    _record_audit(db, _auth["username"], body.tenant_id, body.product,
                  "created", None, body.status, ip=_client_ip(request))
    return lic.to_dict()


@app.put("/api/v1/admin/licenses")
def update_license(body: LicenseCreate, request: Request, db: Session = Depends(get_db),
                   _auth: dict = Depends(require_perm(PERM_LICENSE_MANAGE))):
    lic = _lookup_license(db, body.tenant_id, body.product)
    if not lic:
        raise HTTPException(404, "License not found")
    old_status = lic.status
    lic.status = body.status
    lic.expires_at = body.expires_at
    lic.licensee = body.licensee
    lic.seats = body.seats
    lic.notes = body.notes
    db.commit()
    db.refresh(lic)
    _record_audit(db, _auth["username"], body.tenant_id, body.product,
                  "updated", old_status, body.status, ip=_client_ip(request))
    return lic.to_dict()


@app.delete("/api/v1/admin/licenses")
def delete_license(tenant_id: str, product: str, request: Request, db: Session = Depends(get_db),
                   _auth: dict = Depends(require_perm(PERM_LICENSE_MANAGE))):
    lic = _lookup_license(db, tenant_id, product)
    if not lic:
        raise HTTPException(404, "License not found")
    old_status = lic.status
    db.delete(lic)
    db.commit()
    _record_audit(db, _auth["username"], tenant_id, product,
                  "deleted", old_status, None, ip=_client_ip(request))
    return {"status": "ok"}


@app.get("/api/v1/admin/audit")
def list_audit(db: Session = Depends(get_db), _auth: dict = Depends(require_perm(PERM_AUDIT))):
    rows = db.query(LicenseAudit).order_by(LicenseAudit.id.desc()).limit(200).all()
    return [r.to_dict() for r in rows]


@app.get("/api/v1/admin/admin-audit")
def list_admin_audit(db: Session = Depends(get_db), _auth: dict = Depends(require_perm(PERM_AUDIT))):
    rows = db.query(AdminAudit).order_by(AdminAudit.id.desc()).limit(200).all()
    return [r.to_dict() for r in rows]


# ===========================================================================
# Deployments / Alerts API
# ===========================================================================

@app.get("/api/v1/admin/deployments")
def list_deployments(db: Session = Depends(get_db), _auth: dict = Depends(require_perm(PERM_DEPLOYMENTS))):
    rows = db.query(Deployment).order_by(Deployment.tenant_id).all()
    return [r.to_dict() for r in rows]


@app.get("/api/v1/admin/alerts")
def list_alerts(db: Session = Depends(get_db), _auth: dict = Depends(require_perm(PERM_ALERTS))):
    now = datetime.now(timezone.utc)
    rows = db.query(Deployment).all()
    alerts = []
    for d in rows:
        if not d.last_heartbeat_at:
            sev = "critical"
        else:
            offline_for = (now - _aware(d.last_heartbeat_at)).total_seconds() / 60
            if offline_for >= settings.heartbeat_timeout_minutes:
                sev = "critical"
            elif offline_for >= settings.heartbeat_timeout_minutes * 0.6:
                sev = "warning"
            else:
                continue
        lic = _lookup_license(db, d.tenant_id, d.product)
        alerts.append({
            "tenant_id": d.tenant_id, "product": d.product, "severity": sev,
            "last_seen": d.last_heartbeat_at, "status": lic.status if lic else None,
        })
    return alerts


@app.post("/api/v1/admin/check")
def trigger_check(db: Session = Depends(get_db), _auth: dict = Depends(require_perm(PERM_DEPLOYMENTS))):
    check_deployments()
    return {"status": "ok", "message": "Offline check triggered"}


# ===========================================================================
# User management API (composable roles + extra permissions)
# ===========================================================================

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=64)
    roles: list[str] = Field(default_factory=lambda: [ROLE_OPS])
    extra_permissions: list[str] = Field(default_factory=list)
    is_active: bool = True


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    roles: Optional[list[str]] = None
    extra_permissions: Optional[list[str]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


def _active_super_admin_ids(db: Session) -> list[int]:
    ids = []
    for u in db.query(AdminUser).filter(AdminUser.is_active == True).all():
        roles = [r.strip() for r in (u.roles or u.role or "").split(",") if r.strip()]
        if ROLE_SUPER_ADMIN in roles:
            ids.append(u.id)
    return ids


def _would_orphan_super_admin(db: Session, user: AdminUser, new_roles: Optional[str] = None,
                              active: bool = True) -> bool:
    """True if the change would leave zero active super_admins (lockout)."""
    sa_ids = _active_super_admin_ids(db)
    if user.id not in sa_ids:
        return False
    if len(sa_ids) > 1:
        return False
    # user is the only active super_admin
    if not active:
        return True
    if new_roles is not None:
        roles = [r.strip() for r in new_roles.split(",") if r.strip()]
        if ROLE_SUPER_ADMIN not in roles:
            return True
    return False


@app.get("/api/v1/admin/users")
def list_users(db: Session = Depends(get_db), _auth: dict = Depends(require_perm(PERM_USERS))):
    rows = db.query(AdminUser).order_by(AdminUser.id).all()
    return [r.to_dict() for r in rows]


@app.post("/api/v1/admin/users")
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db),
                _auth: dict = Depends(require_perm(PERM_USERS))):
    ip = _client_ip(request)
    for r in body.roles:
        if r not in ROLE_PERMISSIONS:
            raise HTTPException(400, f"Unknown role: {r}")
    for p in body.extra_permissions:
        if p not in ALL_PERMISSIONS:
            raise HTTPException(400, f"Unknown permission: {p}")
    # Privilege-escalation guard: only super_admin may grant super_admin
    if ROLE_SUPER_ADMIN in body.roles and ROLE_SUPER_ADMIN not in _auth["roles"]:
        raise HTTPException(403, "Only super_admin can assign the super_admin role")
    if db.query(AdminUser).filter(AdminUser.username == body.username).first():
        raise HTTPException(409, "Username already exists")
    user = AdminUser(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.roles[0] if body.roles else ROLE_OPS,
        roles=",".join(body.roles),
        extra_permissions=",".join(body.extra_permissions),
        is_active=body.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _record_admin_audit(
        db, actor=_auth["username"], action="user_created", target=user.username,
        new_roles=user.roles, new_perms=",".join(get_effective_permissions(user)), ip=ip,
    )
    return user.to_dict()


@app.put("/api/v1/admin/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db),
                _auth: dict = Depends(require_perm(PERM_USERS))):
    ip = _client_ip(request)
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    old_roles = user.roles or user.role or ""
    old_perms = ",".join(get_effective_permissions(user))
    new_roles = old_roles
    changed = False

    if body.roles is not None:
        for r in body.roles:
            if r not in ROLE_PERMISSIONS:
                raise HTTPException(400, f"Unknown role: {r}")
        if ROLE_SUPER_ADMIN in body.roles and ROLE_SUPER_ADMIN not in _auth["roles"]:
            raise HTTPException(403, "Only super_admin can assign the super_admin role")
        if _would_orphan_super_admin(db, user, new_roles=",".join(body.roles)):
            raise HTTPException(409, "Cannot remove the last active super_admin")
        user.roles = ",".join(body.roles)
        user.role = body.roles[0] if body.roles else ROLE_OPS
        new_roles = user.roles
        changed = True

    if body.extra_permissions is not None:
        for p in body.extra_permissions:
            if p not in ALL_PERMISSIONS:
                raise HTTPException(400, f"Unknown permission: {p}")
        user.extra_permissions = ",".join(body.extra_permissions)
        changed = True

    if body.display_name is not None:
        user.display_name = body.display_name
        changed = True

    if body.password is not None:
        user.password_hash = hash_password(body.password)
        changed = True

    if body.is_active is not None:
        if body.is_active is False:
            # 末位超管锁优先：停用会导致无可用超管时一律 409
            if _would_orphan_super_admin(db, user, active=False):
                raise HTTPException(409, "Cannot deactivate the last active super_admin")
            if user.id == _auth["uid"]:
                raise HTTPException(400, "You cannot deactivate your own account")
        user.is_active = body.is_active
        changed = True

    db.commit()
    new_perms = ",".join(get_effective_permissions(user))
    if changed:
        _record_admin_audit(
            db, actor=_auth["username"], action="user_updated", target=user.username,
            old_roles=old_roles, new_roles=new_roles,
            old_perms=old_perms, new_perms=new_perms, ip=ip,
        )
    return user.to_dict()


@app.delete("/api/v1/admin/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                _auth: dict = Depends(require_perm(PERM_USERS))):
    ip = _client_ip(request)
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == _auth["uid"]:
        # 末位超管锁优先：删除自己会导致无可用超管时一律 409
        if _would_orphan_super_admin(db, user, active=False):
            raise HTTPException(409, "Cannot delete the last active super_admin")
        raise HTTPException(400, "Cannot delete your own account")
    # 通用末位锁（纵深防御）
    if _would_orphan_super_admin(db, user, active=False):
        raise HTTPException(409, "Cannot delete the last active super_admin")
    old_roles = user.roles or user.role or ""
    old_perms = ",".join(get_effective_permissions(user))
    db.delete(user)
    db.commit()
    _record_admin_audit(
        db, actor=_auth["username"], action="user_deleted", target=user.username,
        old_roles=old_roles, old_perms=old_perms, ip=ip,
    )
    return {"status": "ok"}
