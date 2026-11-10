from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class UserInfo(BaseModel):
    id: int
    tenant_id: str
    username: str
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    status: str
    roles: List[str] = []
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class CreateUserRequest(BaseModel):
    username: str
    password: str
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role_ids: Optional[List[int]] = None
    # ── B7/B9: 组织归属（主组织 + 兼任）──
    org_id: Optional[int] = None
    """主组织 ID（写入 users.primary_org_id 与 user_organizations.is_primary=1）"""
    org_ids: Optional[List[int]] = None
    """兼任组织 ID 列表（is_primary=0）"""
    cloud_uuid: Optional[str] = None
    """cloud.ziwi.cn 用户 UUID（管理员手绑；首登自动建户走 B15 的 dependencies 分支）"""


class UpdateUserRequest(BaseModel):
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    org_id: Optional[int] = None
    """变更主组织：写入 users.primary_org_id 并同步 user_organizations"""
    org_ids: Optional[List[int]] = None
    """全量兼任组织（与 org_id 合并为目标集合，其余旧关联被删除）"""
    role_ids: Optional[List[int]] = None
    """全量同步角色（D-B2：与创建对齐，传 [] 即清空全部角色）"""
    work_center_ids: Optional[List[int]] = None
    """全量同步**账号绑定的工作中心**（报工台的按工位可见范围）。

    ★ 三种取值语义必须分开，合并成一个"空就是清空"会让"改个手机号"
      顺手抹掉工位绑定 —— 而绑定没了等于**权限面扩大**（从只看两个工位
      变成看全厂），且没有任何提示：
      - 不传（None）→ 不动
      - ``[]``      → 解绑全部（回到"不限工位"）
      - ``[3,5]``   → 只保留这两个
    """
    force: Optional[bool] = False
    """A-E4：名下仍有在办单据时是否强制停用。默认 false —— 让人先转交，
    逼着操作者看一眼「这几张单子还没人接」。强制停用会写审计留痕。"""


class UserOrgResponse(BaseModel):
    """用户组织归属响应片段。"""

    primary_org_id: Optional[int] = None
    org_id: Optional[int] = None
    org_ids: List[int] = []


class UserDetailResponse(UserInfo):
    """B9: 用户详情（含组织归属）。"""

    primary_org_id: Optional[int] = None
    org_id: Optional[int] = None
    org_ids: List[int] = []
    org_name: Optional[str] = None
"""B13 说明：org_name 依赖任务 B3 新建的 organizations 表，本轮整个任务链未落地，
字段先以 None 占位，B3 建表后由 user_repo 的 JOIN 回填。"""
