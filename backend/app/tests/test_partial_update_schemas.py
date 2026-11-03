"""主数据「部分更新」与「service→repo 方法存在性」的跨文件契约。

这一组守的是三种**测不出来但天天踩**的形态：

1. **PUT 复用 Create schema** —— Create 里的必填字段会变成 PUT 的必填字段，
   于是"只改一个字段"的提交被 Pydantic 挡成 422（`missing part_code`）。
   前端要么把整条记录回传（容易把没加载到的字段写成 null），
   要么干脆不做编辑入口。已踩：`/wms/data-sources`、`/spare-parts`、
   `/energy/devices`。

2. **service 调了一个仓储层不存在的方法** —— 静态看不出、单测看不出
   （mock 的 repo 什么方法都有），只有真打一次接口才 500。
   已踩：`TpmService.update_task_status` → `TpmRepository.update_task_status`
   （仓储层压根没有这个方法，AttributeError → 500）。

3. 空载荷的 PUT —— `_build_set_clause({})` 拼出 `SET  WHERE` → SQL 语法错。
"""
from unittest.mock import AsyncMock

import pytest

from app.repositories.tpm_repo import TpmRepository
from app.schemas.energy import CreateEnergyDeviceRequest, UpdateEnergyDeviceRequest
from app.schemas.tpm import CreateSparePartRequest, UpdateSparePartRequest


def _required_fields(model) -> set:
    return {n for n, f in model.model_fields.items() if f.is_required()}


# ── 1. PUT 用的 schema 不能有必填字段 ────────────────────────────────

class TestPartialUpdateSchemas:
    def test_spare_part_update_has_no_required_fields(self):
        assert _required_fields(UpdateSparePartRequest) == set(), (
            "Update* 有必填字段 → 只改一个字段的 PUT 会被 422 挡掉")

    def test_energy_device_update_has_no_required_fields(self):
        assert _required_fields(UpdateEnergyDeviceRequest) == set()

    def test_update_models_construct_empty(self):
        """空 body 必须能构造出来（接口层再短路成 200 无变更）。"""
        assert UpdateSparePartRequest().model_dump(exclude_unset=True) == {}
        assert UpdateEnergyDeviceRequest().model_dump(exclude_unset=True) == {}

    def test_create_still_requires_its_fields(self):
        """别为了修 PUT 把 Create 的校验一起放松了。"""
        assert {"part_code", "part_name"} <= _required_fields(CreateSparePartRequest)
        assert {"device_code", "device_name", "device_type", "energy_type"} <= \
            _required_fields(CreateEnergyDeviceRequest)

    def test_partial_payload_only_carries_given_fields(self):
        payload = UpdateSparePartRequest(min_stock=8).model_dump(exclude_unset=True)
        assert payload == {"min_stock": 8}, (
            "exclude_unset 必须只带用户真正给的字段，否则会把没传的列刷成 NULL")


# ── 2. service 依赖的仓储方法必须真的存在 ────────────────────────────

class TestRepoMethodExists:
    def test_tpm_repo_has_update_task_status(self):
        """`TpmService.update_task_status` 直接调 `repo.update_task_status`。

        仓储层没有这个方法时，任何非 in_progress/completed 的状态修改都会
        AttributeError → 500。正常执行走 start/complete 两条联动路径，
        所以这条老接口只有"取消 / 驳回"才会走到 —— 没有页面入口、
        也没有探针，于是一直坏着。
        """
        assert hasattr(TpmRepository, "update_task_status"), (
            "TpmRepository 缺 update_task_status → PUT /maintenance-tasks/{id}/status 500")


class TestUpdateTaskStatusSql:
    pytestmark = pytest.mark.asyncio

    async def test_update_task_status_executes_one_update(self):
        repo = TpmRepository.__new__(TpmRepository)
        repo.execute = AsyncMock(return_value=1)
        affected = await repo.update_task_status(7, "canceled")
        assert affected == 1
        sql, params = repo.execute.await_args.args[:2]
        assert sql.strip().upper().startswith("UPDATE MAINTENANCE_TASKS SET STATUS")
        assert params == {"status": "canceled", "id": 7}
