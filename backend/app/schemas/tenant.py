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


class InitAdminRequest(BaseModel):
    """A-S1: 为已开通租户初始化管理员账号。

    开通租户（POST /tenants）与初始化管理员分开成两步，是为了让"建租户"和
    "发初始密码"这两件事能被分别审计 —— 后者会经邮件/微信转交到客户手上，
    是整条链上唯一"密码离开系统"的环节。
    """

    username: str = Field(..., description="管理员登录名（租户内唯一）")
    password: str = Field(..., min_length=8, description="初始密码，至少 8 位；首登必须修改")
    real_name: Optional[str] = Field(None, description="管理员姓名")


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
