from app.repositories.organization_repo import OrganizationRepository
from app.constants.modules import (
    ORG_CHILD_TYPES, ORG_COMPANY, ORG_STATUS_ACTIVE, ORG_STATUS_DISABLED,
    ORG_TYPES, SCOPE_ALL, SCOPE_DEPT, SCOPE_DEPT_CHILD, SCOPE_SELF,
)
from typing import Optional, List, Dict

from fastapi import HTTPException


class OrganizationService:
    def __init__(self, repo: OrganizationRepository):
        self.repo = repo

    async def list_teams(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.repo.list_teams(page, page_size)

    async def create_team(self, data: dict) -> dict:
        return {"id": await self.repo.create_team(data)}

    async def list_employees(self, page: int = 1, page_size: int = 20, team_id: int = None) -> dict:
        return await self.repo.list_employees(page, page_size, team_id)

    async def create_employee(self, data: dict) -> dict:
        return {"id": await self.repo.create_employee(data)}

    async def update_employee(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_employee(id, data)}

    async def delete_employee(self, id: int) -> int:
        return await self.repo.delete_employee(id)

    # ============================================================
    # B3：组织树（公司 / 车间 / 部门 / 班组）
    # ============================================================

    async def list_tree(self) -> List[Dict]:
        """返回扁平列表（按 path 先序），前端自行组树。

        选择扁平而非嵌套的原因：前端已有 van-tree-select 等组件可消费扁平数据，
        且扁平结构便于"移动节点后局部刷新"。
        """
        rows = await self.repo.list_all_orgs()
        counts = {}
        for r in rows:
            counts[r["id"]] = r
        result = []
        for r in rows:
            item = dict(r)
            item["has_children"] = any(x["parent_id"] == r["id"] for x in rows)
            result.append(item)
        return result

    async def list_page(self, page: int, page_size: int,
                        keyword: str = None, org_type: str = None) -> dict:
        return await self.repo.list_orgs_page(page, page_size, keyword, org_type)

    async def get(self, org_id: int) -> Dict:
        org = await self.repo.get_org(org_id)
        if not org:
            raise HTTPException(404, detail={"code": "404-0000", "message": "组织不存在"})
        return org

    async def create(self, data: dict, tenant_id: str) -> Dict:
        """新建组织节点。

        校验（对应场景 A-S2 / A-E1）：
        1. org_type 合法
        2. code 租户内唯一
        3. 父节点存在；父类型允许挂本类型（ORG_CHILD_TYPES 白名单）
        4. path 在拿到自增 id 后回填为 ``{parent_path}/{id}`` 或 ``{id}``（根）
        """
        org_type = data.get("org_type")
        if org_type not in ORG_TYPES:
            raise HTTPException(400, detail={
                "code": "400-0001",
                "message": f"组织类型非法: {org_type}（允许 {list(ORG_TYPES)}）",
            })

        code = (data.get("code") or "").strip()
        if not code:
            raise HTTPException(400, detail={"code": "400-0001", "message": "组织编码不能为空"})
        if await self.repo.get_org_by_code(code):
            raise HTTPException(400, detail={
                "code": "400-0002", "message": f"组织编码已存在: {code}",
            })

        parent_id = data.get("parent_id")
        parent = None
        if parent_id:
            parent = await self.repo.get_org(parent_id)
            if not parent:
                raise HTTPException(400, detail={
                    "code": "400-0003", "message": f"父组织不存在: {parent_id}",
                })
            allowed = ORG_CHILD_TYPES.get(parent["org_type"], ())
            if org_type not in allowed:
                raise HTTPException(400, detail={
                    "code": "400-0004",
                    "message": f"{parent['org_type']} 下不允许挂 {org_type}（允许 {list(allowed) or '无'}）",
                })

        payload = {
            "tenant_id": tenant_id,
            "parent_id": parent_id,
            "code": code,
            "name": data["name"],
            "org_type": org_type,
            "level": (parent["level"] + 1) if parent else 1,
            "sort_order": data.get("sort_order", 0),
            "leader_user_id": data.get("leader_user_id"),
            "status": data.get("status", ORG_STATUS_ACTIVE),
            "remark": data.get("remark"),
        }
        new_id = await self.repo.insert_org(payload)
        # 回填物化路径
        path = f"{parent['path']}/{new_id}" if parent else str(new_id)
        await self.repo.set_org_path(new_id, path, payload["level"])
        return {"id": new_id, "path": path, "level": payload["level"]}

    async def update(self, org_id: int, data: dict) -> Dict:
        """更新组织字段（不含 parent_id —— 移动走 move 接口并重算子树 path）。"""
        org = await self.get(org_id)
        allowed_fields = {"name", "code", "sort_order", "leader_user_id", "status", "remark"}
        payload = {k: v for k, v in data.items() if k in allowed_fields and v is not None}

        if "code" in payload and payload["code"] != org["code"]:
            if await self.repo.get_org_by_code(payload["code"]):
                raise HTTPException(400, detail={
                    "code": "400-0002", "message": f"组织编码已存在: {payload['code']}",
                })
        if "status" in payload and payload["status"] not in (ORG_STATUS_ACTIVE, ORG_STATUS_DISABLED):
            raise HTTPException(400, detail={"code": "400-0001", "message": "状态非法"})
        if not payload:
            return {"affected": 0}

        affected = await self.repo.update_org(org_id, payload)
        return {"affected": affected}

    async def move(self, org_id: int, new_parent_id: Optional[int]) -> Dict:
        """移动节点到新父级，并重算整棵子树的 path / level。

        防成环：新父不能是自己，也不能是自己的子孙（新父 path 以自己 path 开头）。
        """
        org = await self.get(org_id)

        new_parent = None
        if new_parent_id is not None:
            new_parent = await self.repo.get_org(new_parent_id)
            if not new_parent:
                raise HTTPException(400, detail={"code": "400-0003", "message": "目标父组织不存在"})
            if new_parent["id"] == org_id:
                raise HTTPException(400, detail={"code": "400-0005", "message": "不能把组织挂到自己下面"})
            if new_parent["path"] == org["path"] or new_parent["path"].startswith(f"{org['path']}/"):
                raise HTTPException(400, detail={
                    "code": "400-0005", "message": "不能把组织挂到自己的子孙下面（会成环）",
                })
            allowed = ORG_CHILD_TYPES.get(new_parent["org_type"], ())
            if org["org_type"] not in allowed:
                raise HTTPException(400, detail={
                    "code": "400-0004",
                    "message": f"{new_parent['org_type']} 下不允许挂 {org['org_type']}",
                })

        old_path = org["path"]
        new_path = f"{new_parent['path']}/{org_id}" if new_parent else str(org_id)
        new_level = (new_parent["level"] + 1) if new_parent else 1
        level_delta = new_level - org["level"]

        # 1) 先改自己
        await self.repo.update_org(org_id, {"parent_id": new_parent_id})
        await self.repo.set_org_path(org_id, new_path, new_level)

        # 2) 再平移所有子孙：把 prefix 从 old_path 换成 new_path
        descendants = await self.repo.list_org_subtree(old_path, include_self=False)
        moved = 0
        for d in descendants:
            d_path = f"{new_path}{d['path'][len(old_path):]}"
            await self.repo.set_org_path(d["id"], d_path, d["level"] + level_delta)
            moved += 1

        return {"id": org_id, "path": new_path, "level": new_level, "descendants_moved": moved}

    async def delete(self, org_id: int) -> Dict:
        """删除组织（A-E1：存在子节点或成员时拒绝，不用级联删）。

        拒绝而非级联的理由：组织被误删会导致 user_organizations / 数据范围静默失真，
        宁可让操作者先把人挪走。
        """
        org = await self.get(org_id)
        child_count = await self.repo.count_org_children(org_id)
        if child_count > 0:
            raise HTTPException(409, detail={
                "code": "409-0001",
                "message": f"该组织下还有 {child_count} 个子组织，请先删除或移走子组织",
            })
        member_count = await self.repo.count_org_members(org_id)
        if member_count > 0:
            raise HTTPException(409, detail={
                "code": "409-0002",
                "message": f"该组织下还有 {member_count} 名成员，请先调整成员归属",
            })
        affected = await self.repo.delete_org(org_id)
        return {"affected": affected, "code": org["code"]}

    # ---------- 成员 ----------

    async def list_members(self, org_id: int) -> List[Dict]:
        await self.get(org_id)   # 存在性校验
        return await self.repo.list_org_members(org_id)

    async def add_member(self, org_id: int, user_id: int, tenant_id: str,
                         is_primary: bool = False) -> Dict:
        await self.get(org_id)
        affected = await self.repo.add_org_member(tenant_id, user_id, org_id, is_primary)
        return {"affected": affected}

    async def remove_member(self, org_id: int, user_id: int) -> Dict:
        return {"affected": await self.repo.remove_org_member(user_id, org_id)}

    # ---------- 数据范围解析 ----------

    async def resolve_scope_org_ids(self, user_id: int, scope: str) -> Optional[List[int]]:
        """把角色的数据范围解析成"可见组织 id 列表"。

        - ALL         → ``None``（表示不加组织过滤）
        - SELF        → ``[]``（调用方应改用 created_by/reporter 过滤；本方法只给组织维度）
        - DEPT        → 用户所属组织 id 列表
        - DEPT_CHILD  → 用户所属组织 + 其全部子孙组织 id

        用户没有任何组织归属时，退回 ``None``（不误伤，避免"新用户看不到任何数据"）。
        """
        if scope == SCOPE_ALL:
            return None
        my_org_ids = await self.repo.user_org_ids(user_id)
        if not my_org_ids:
            return None
        if scope == SCOPE_DEPT:
            return my_org_ids

        # DEPT_CHILD
        all_ids: set = set(my_org_ids)
        for oid in my_org_ids:
            org = await self.repo.get_org(oid)
            if not org:
                continue
            subtree = await self.repo.list_org_subtree(org["path"], include_self=True)
            all_ids.update(int(s["id"]) for s in subtree)
        return sorted(all_ids)
