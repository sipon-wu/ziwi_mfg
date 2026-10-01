from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime


class TenantResponse(BaseModel):
    id: int
    tenant_id: str
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    status: str
    industry: Optional[str] = None
    region: Optional[str] = None
    expire_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateTenantRequest(BaseModel):
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    industry: Optional[str] = None
    region: Optional[str] = None


class UpdateTenantRequest(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    industry: Optional[str] = None
    region: Optional[str] = None


class SetModulesRequest(BaseModel):
    """B2: 模块启停写回请求体。

    module_codes 为「已启用的 feature_flags 扁平键」数组，例如：
        ["M01_WORK_ORDER", "M01_WORK_REPORT", "M02_EQUIPMENT"]
    对应 package_modules 嵌套结构：
        {"M01": ["WORK_ORDER", "WORK_REPORT"], "M02": ["EQUIPMENT"]}

    未列出的子功能视为关闭（从 package_modules 中移除，get_feature_flags 不再返回 True）。
    """

    module_codes: List[str] = Field(default_factory=list, description="启用的模块功能编码列表")


class TenantModulesResponse(BaseModel):
    """B2: 模块启停写回结果。"""

    package_modules: dict
    affected: int


class TenantModulesGetResponse(BaseModel):
    """B2: 当前租户已启用模块查询（供前端模块开关页回填）。"""

    module_codes: List[str]
    feature_flags: dict
