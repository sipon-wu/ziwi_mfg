from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.core.security import hash_password
from typing import Optional


# A-E4：把人停用之前，必须先看他手上还压着什么。
# 覆盖五类最常见的「有主在办」单据 —— 选这五类而不是全库扫，是因为只有它们
# 明确带「指派人 + 未完成状态」两个字段：工单（生产执行的主体）、检验单
# （待检 = 有人要判）、审批节点（待审 = 流程卡在这一步）、保养任务（待做/在做）、
# NCR（未关闭 = 质量闭环没走完）。
# 停用之后这些单据不会消失，只会变成"挂着一个人名的僵尸单"：谁也看不到、
# 谁也接不了，直到有人翻库才发现。
_INACTIVE_STATUSES = {"inactive", "disabled", "locked"}

_OPEN_DOC_QUERIES = [
    ("工单", "SELECT COUNT(*) AS c FROM work_orders "
             "WHERE assignee_id = :uid "
             "AND wo_status IN ('released', 'in_progress', 'paused')"),
    ("检验单", "SELECT COUNT(*) AS c FROM inspection_order "
               "WHERE inspector_id = :uid "
               "AND (result IS NULL OR result = 'pending')"),
    ("待审批节点", "SELECT COUNT(*) AS c FROM approval_nodes "
                   "WHERE approver_id = :uid AND status = 'pending' "
                   "AND node_type = 'approve'"),
    ("保养任务", "SELECT COUNT(*) AS c FROM maintenance_tasks "
                 "WHERE assignee_id = :uid AND status IN ('pending', 'in_progress')"),
    ("未关闭 NCR", "SELECT COUNT(*) AS c FROM ncr_records "
                   "WHERE raised_by = :uid "
                   "AND status NOT IN ('closed', 'cancelled')"),
]


class UserService:
    def __init__(self, user_repo: UserRepository, role_repo: RoleRepository):
        self.user_repo = user_repo
        self.role_repo = role_repo

    async def list(self, page: int = 1, page_size: int = 20, keyword: str = None, status: str = None) -> dict:
        return await self.user_repo.list(page, page_size, keyword, status)

    async def get(self, id: int) -> Optional[dict]:
        return await self.user_repo.get(id)

    async def create(self, data: dict) -> dict:
        # D-B2: role_ids 单独消费（repo 的 INSERT 是固定列，传进去会被静默丢弃）
        role_ids = data.pop("role_ids", None)
        data["password_hash"] = hash_password(data.pop("password"))
        # create 走 INSERT ... RETURNING id，返回值即新用户 PK
        user_id = await self.user_repo.create(data)
        result = {"affected": 1, "id": user_id}
        if role_ids is not None:
            result["roles"] = await self.user_repo.sync_user_roles(user_id, role_ids)
        return result

    async def open_documents(self, user_id: int) -> list:
        """A-E4：查该用户名下还有哪些在办单据（停用前必须先转交）。"""
        found = []
        for label, sql in _OPEN_DOC_QUERIES:
            try:
                row = await self.user_repo.query_one(sql, {"uid": user_id})
            except Exception:  # noqa: BLE001 —— 老库缺表不该让改用户直接崩
                continue
            cnt = (row or {}).get("c") or 0
            if cnt:
                found.append({"type": label, "count": int(cnt)})
        return found

    async def update(self, id: int, data: dict) -> dict:
        # B9: 组织归属字段不参与 users 表通用 SET（由 user_organizations 单独维护）
        org_id = data.pop("org_id", None)
        org_ids = data.pop("org_ids", None)
        # D-B2: 角色变更同样走同步（不进 users 表 SET）
        role_ids = data.pop("role_ids", None)
        if "password" in data:
            data["password_hash"] = hash_password(data.pop("password"))

        # 空 SET 会生成 "UPDATE users SET  WHERE ..." 这种非法 SQL，纯组织变更时必须跳过
        # ── A-E4：停用前先看手上还压着什么 ─────────────────────
        # 改造前 `PUT /users/{id} {"status":"inactive"}` 一律 200「更新成功」，
        # 哪怕这个人名下还有 3 张在制工单 —— 停用后这些单子变成"挂着人名
        # 的僵尸单"：谁也看不到、谁也接不了，直到有人翻库才发现。
        force = bool(data.pop("force", False))
        new_status = data.get("status")
        if new_status in _INACTIVE_STATUSES:
            docs = await self.open_documents(id)
            if docs and not force:
                detail = "、".join(f"{d['type']} {d['count']} 张" for d in docs)
                raise ValueError(
                    f"该用户名下还有在办单据（{detail}），不能直接停用；"
                    f"请先转交或办结。确需立即停用请显式传 force=true")
            if docs and force:
                # 强制停用要留痕：事后追"谁在什么情况下把人停了"只有这一处证据
                try:
                    from app.services.audit_service import AuditService
                    await AuditService(self.user_repo._session).log(
                        "user.force_disable",
                        tenant_id=getattr(self.user_repo, "tenant_id", None),
                        object_type="user", object_id=id,
                        after={"status": new_status, "open_documents": docs},
                        message=("强制停用用户（名下仍有在办单据）："
                                 + "、".join(f"{d['type']} {d['count']} 张" for d in docs)),
                    )
                except Exception:  # noqa: BLE001 —— 审计不可用不阻断
                    pass
                result_extra = {"forced_open_documents": docs}
            else:
                result_extra = {}
        else:
            result_extra = {}

        count = await self.user_repo.update(id, data) if data else 0

        result = {"affected": count, **result_extra}
        if org_id is not None or org_ids is not None:
            sync = await self.user_repo.sync_user_orgs(id, org_id, org_ids)
            # users.primary_org_id 与 user_organizations 保持一致
            if sync.get("primary_org_id") is not None or org_id is None:
                primary = await self.user_repo.update(id, {"primary_org_id": sync["primary_org_id"]})
                result["affected"] = (result["affected"] or 0) + (primary or 0)
            result["org"] = sync
        if role_ids is not None:
            result["roles"] = await self.user_repo.sync_user_roles(id, role_ids)
        return result

    async def delete(self, id: int, force: bool = False) -> dict:
        """删除用户 —— 与停用同一条守卫（A-E4 同源）。

        停用至少人还在、还能查；**删除更彻底**：工单 `assignee_id` 从此指向
        一个不存在的 id，车间看不到「这活派给谁了」，系统里也再没有地方能
        回答。所以有在办单据时一律 409，确需删除必须显式 ``force``。
        """
        docs = await self.open_documents(id)
        if docs and not force:
            detail = "、".join(f"{d['type']} {d['count']} 张" for d in docs)
            raise ValueError(
                f"该用户名下还有在办单据（{detail}），不能直接删除；"
                f"请先转交或办结，或改用停用（可恢复）。"
                f"确需立即删除请显式传 force=true")
        extra = {}
        if docs and force:
            try:
                from app.services.audit_service import AuditService
                await AuditService(self.user_repo._session).log(
                    "user.force_delete",
                    tenant_id=getattr(self.user_repo, "tenant_id", None),
                    object_type="user", object_id=id,
                    after={"open_documents": docs},
                    message=("强制删除用户（名下仍有在办单据，单据负责人将悬空）："
                             + "、".join(f"{d['type']} {d['count']} 张" for d in docs)),
                )
            except Exception:  # noqa: BLE001 —— 审计不可用不阻断
                pass
            extra = {"forced_open_documents": docs}
        count = await self.user_repo.delete(id)
        return {"affected": count, **extra}
