"""
Heartbeat Service — SQLAlchemy Models.

Includes Deployments, Licenses, LicenseAudit, LoginAttempt and AdminUser tables.
"""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)


# ============================================================
# RBAC — Roles & Permissions
# ============================================================

ROLE_SUPER_ADMIN = "super_admin"
ROLE_OPS = "ops"
ROLE_SALES = "sales"
ROLE_FINANCE = "finance"
ROLE_SUPPORT = "support"  # 预留占位

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "超级管理员",
    ROLE_OPS: "运营",
    ROLE_SALES: "销售",
    ROLE_FINANCE: "财务",
    ROLE_SUPPORT: "实施",
}

# Permission points
PERM_DASHBOARD = "dashboard"
PERM_LICENSE_VIEW = "license_view"
PERM_LICENSE_MANAGE = "license_manage"
PERM_DEPLOYMENTS = "deployments"
PERM_ALERTS = "alerts"
PERM_CUSTOMERS = "customers"
PERM_AUDIT = "audit"
PERM_USERS = "users"
PERM_SETTINGS = "settings"

# Role → permission map
ROLE_PERMISSIONS = {
    ROLE_SUPER_ADMIN: [
        PERM_DASHBOARD, PERM_LICENSE_VIEW, PERM_LICENSE_MANAGE,
        PERM_DEPLOYMENTS, PERM_ALERTS, PERM_CUSTOMERS,
        PERM_AUDIT, PERM_USERS, PERM_SETTINGS,
    ],
    ROLE_OPS: [
        PERM_DASHBOARD, PERM_LICENSE_VIEW, PERM_LICENSE_MANAGE,
        PERM_DEPLOYMENTS, PERM_ALERTS, PERM_CUSTOMERS, PERM_AUDIT,
    ],
    ROLE_SALES: [
        PERM_DASHBOARD, PERM_LICENSE_VIEW, PERM_LICENSE_MANAGE, PERM_CUSTOMERS,
    ],
    ROLE_FINANCE: [
        PERM_DASHBOARD, PERM_LICENSE_VIEW, PERM_CUSTOMERS,
    ],
    ROLE_SUPPORT: [],  # 预留占位
}

# Permission point labels (for UI assignment)
PERM_LABELS = {
    PERM_DASHBOARD: "仪表盘",
    PERM_LICENSE_VIEW: "查看授权",
    PERM_LICENSE_MANAGE: "管理授权",
    PERM_DEPLOYMENTS: "部署状态",
    PERM_ALERTS: "告警中心",
    PERM_CUSTOMERS: "客户视图",
    PERM_AUDIT: "审计日志",
    PERM_USERS: "用户管理",
    PERM_SETTINGS: "系统设置",
}

# All known permission points (union of role permissions)
ALL_PERMISSIONS = sorted({p for perms in ROLE_PERMISSIONS.values() for p in perms})


def get_effective_permissions(user) -> list:
    """Composable permission resolution.

    Effective permissions = union(roles' permissions) + direct extra_permissions.
    Legacy single `role` column is used as fallback when `roles` is empty.
    """
    roles: list[str] = []
    raw_roles = getattr(user, "roles", None)
    if raw_roles:
        roles = [r.strip() for r in raw_roles.split(",") if r.strip()]
    if not roles:
        legacy = getattr(user, "role", None)
        if legacy:
            roles = [legacy]
    perms: set[str] = set()
    for r in roles:
        perms.update(ROLE_PERMISSIONS.get(r, []))
    extra = getattr(user, "extra_permissions", None) or ""
    for p in extra.split(","):
        p = p.strip()
        if p:
            perms.add(p)
    # Only keep well-known permission points
    return sorted(perms & set(ALL_PERMISSIONS))


# Navigation menu definition (ordered)
NAV_ITEMS = [
    {"key": "dashboard", "label": "仪表盘", "icon": "grid", "perm": PERM_DASHBOARD, "path": "/admin"},
    {"key": "licenses", "label": "License 管理", "icon": "key", "perm": PERM_LICENSE_VIEW, "path": "/admin/licenses"},
    {"key": "customers", "label": "客户视图", "icon": "users", "perm": PERM_CUSTOMERS, "path": "/admin/customers"},
    {"key": "deployments", "label": "部署状态", "icon": "server", "perm": PERM_DEPLOYMENTS, "path": "/admin/deployments"},
    {"key": "alerts", "label": "告警中心", "icon": "bell", "perm": PERM_ALERTS, "path": "/admin/alerts"},
    {"key": "audit", "label": "审计日志", "icon": "shield", "perm": PERM_AUDIT, "path": "/admin/audit"},
    {"key": "users", "label": "用户管理", "icon": "user-cog", "perm": PERM_USERS, "path": "/admin/users"},
    {"key": "settings", "label": "系统设置", "icon": "cog", "perm": PERM_SETTINGS, "path": "/admin/settings"},
    {"key": "support", "label": "实施工作台", "icon": "tools", "perm": None, "path": "/admin/support", "placeholder": True},
]


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 password hashing (no external dependency)."""
    salt = secrets.token_hex(16)
    pwdhash = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000)
    return f"pbkdf2_sha256${salt}${pwdhash.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored PBKDF2 hash."""
    try:
        _, salt, pwdhash = stored.split("$")
        new_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000)
        return secrets.compare_digest(new_hash.hex(), pwdhash)
    except Exception:
        return False


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""
    pass


class AdminAudit(Base):
    """Audit trail for operator account & permission changes (non-repudiation)."""

    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_user: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_roles: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    new_roles: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    old_perms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_perms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor": self.actor,
            "action": self.action,
            "target_user": self.target_user,
            "old_roles": self.old_roles,
            "new_roles": self.new_roles,
            "old_perms": self.old_perms,
            "new_perms": self.new_perms,
            "ip_address": self.ip_address,
            "created_at": self.created_at,
        }


# ============================================================
# Database engine & session
# ============================================================


def init_db(database_path: str) -> tuple:
    """Create engine and session factory from a database path."""
    import os
    _db_dir = os.path.dirname(database_path)
    if _db_dir:
        os.makedirs(_db_dir, exist_ok=True)

    url = f"sqlite:///{database_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, SessionLocal


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
    product: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    license_issued_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    license_expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="offline")
    consecutive_misses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
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
    """License authority — authoritative source of license state.

    A tenant may hold multiple products (e.g. mfg + school) in parallel, so
    uniqueness is enforced on (tenant_id, product), NOT tenant_id alone.
    """

    __tablename__ = "licenses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product", name="uq_license_tenant_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    product: Mapped[str] = mapped_column(String(32), nullable=False, default="school")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    licensee: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    seats: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    heartbeats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "product": self.product,
            "status": self.status,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "licensee": self.licensee,
            "seats": self.seats,
            "notes": self.notes,
            "last_seen": self.last_seen,
            "last_version": self.last_version,
            "heartbeats": self.heartbeats,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class LicenseAudit(Base):
    """Immutable audit trail for all license changes."""

    __tablename__ = "license_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # action: created / updated / activated / deactivated / renewed / status_changed
    old_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    old_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    new_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="admin")
    # "admin" (UI login) or "api:<ip>" (X-Api-Key) or "system"
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "product": self.product,
            "action": self.action,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "old_expires_at": self.old_expires_at,
            "new_expires_at": self.new_expires_at,
            "changed_by": self.changed_by,
            "ip_address": self.ip_address,
            "detail": self.detail,
            "created_at": self.created_at,
        }


class LoginAttempt(Base):
    """Tracks failed login attempts for brute-force protection."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )


class AdminUser(Base):
    """Platform operator accounts with role-based access control."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Legacy single role (kept for backward-compat; effective auth uses `roles`)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_OPS)
    # Composable assignment: comma-separated role list + directly-granted perms
    roles: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extra_permissions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        roles = [r.strip() for r in (self.roles or "").split(",") if r.strip()]
        if not roles:
            roles = [self.role] if self.role else []
        role_labels = [ROLE_LABELS.get(r, r) for r in roles]
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "roles": roles,
            "role_labels": role_labels,
            "role_label": " / ".join(role_labels) or "—",
            "extra_permissions": [p.strip() for p in (self.extra_permissions or "").split(",") if p.strip()],
            "effective_permissions": get_effective_permissions(self),
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }
