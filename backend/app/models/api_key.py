"""Integration Gateway — API Key 模型（IG MVP）。

设计要点（对齐 June 2026-06 评估 §4.3）：
- 以 API Key 作为第三方系统（OA / HR / LIMS / ERP）对接 mfg 的认证原语；
- 明文 Key 仅创建时返回一次，库内只存 bcrypt 哈希 + 前缀（用于 O(1) 定位）；
- 租户隔离沿用 MultiTenantRepository（api_keys 表含 tenant_id）；
- webhook_url 列预留给 Phase 2 Webhook 回调（本轮 MVP 仅建列，不接路由）。
"""
from sqlalchemy import (
    Column, BigInteger, String, Boolean, DateTime, Text,
)
from sqlalchemy.sql import func
from app.core.database import Base


# API Key 格式：ziwi_<48 位 hex>，前缀取前 12 字符用于定位记录
API_KEY_PREFIX_LEN = 12


class ApiKey(Base):
    """租户级 API 密钥"""
    __tablename__ = "api_keys"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, index=True, comment="租户ID")
    key_name = Column(String(100), nullable=False, comment="密钥名称（便于识别用途）")
    key_prefix = Column(String(32), nullable=False, index=True, comment="密钥前缀（明文前 12 位）")
    key_hash = Column(String(200), nullable=False, comment="bcrypt 哈希（明文永不入库）")
    permissions = Column(Text, comment="授权范围 JSON 数组，如 [\"trials:read\",\"lab:write\"]")
    allowed_ips = Column(Text, comment="IP 白名单 JSON 数组，空数组=不限制")
    webhook_url = Column(String(500), comment="（Phase 2）Webhook 回调地址，预留列")
    is_active = Column(Boolean, default=True, comment="是否启用")
    expires_at = Column(DateTime(timezone=True), comment="过期时间（可空=永不过期）")
    last_used_at = Column(DateTime(timezone=True), comment="最近使用时间")
    created_by = Column(BigInteger, comment="创建人用户ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
