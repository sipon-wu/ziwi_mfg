"""Refresh token rotation model (RFC 9700)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.user import Base


class RefreshTokenRecord(Base):
    """Tracks refresh token lifecycle for rotation and replay detection.

    Each refresh_token is identified by a unique ``jti`` (JWT ID).  Tokens
    belonging to the same rotation chain share a common ``family_id``.

    Status lifecycle:
        ``active`` → ``used`` (normal rotation)
        ``active``/``used`` → ``revoked`` (replay detected — whole family)
    """

    __tablename__ = "refresh_token_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
        comment="JWT ID — uniquely identifies a single refresh_token issuance",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    family_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="Token family — shared by all tokens in the same rotation chain",
    )
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False,
        comment="active | used | revoked",
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # TODO: 定期清理 expires_at < now() 且 status != "active" 的记录
    #       （可通过 cron 或 db 定时任务）

    def __repr__(self) -> str:
        return f"<RefreshTokenRecord jti={self.jti!r} status={self.status!r}>"
