"""`ProductionService.report_step` 的编排单测。

为什么单独测这一层：`report_step` 本身几乎没有"逻辑"，它做的是**转交**——
把路径里的 `order_id` + `step_seq` 解析成工序，再补齐 `operation_code` 后
交给既有的 `create_report`。这类代码错了不报错，只会把产量记到别处：

- 工序编码如果仍由用户填，打错了要记到另一道工序上，或者"对不上任何工序"
  变成静默的报整单 —— 两者都返回 200，产量数字错，事后无从追溯。
- `report_date` 不兜底成业务日，补录的行会落到容器 UTC 的"今天"，
  在 UTC 16:00–24:00 之间整整早一天。

所以这里钉的就是这两件"看着没事、其实错了"的事。
"""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.business_time import business_today
from app.services.production_service import ProductionService

STEP = {
    "id": 77,
    "work_order_id": 9,
    "step_seq": 3,
    "operation_code": "CW010",
    "operation_name": "车削",
    "wc_id": 12,
    "planned_qty": 30,
}

SERVICE = "app.services.production_service.ProductionService"


def _svc(step=STEP):
    """构造一个只关心 `get_step` 的服务实例，`create_report` 由用例自己打桩。"""
    repo = AsyncMock()
    repo.get_step = AsyncMock(return_value=step)
    return ProductionService(repo)


class TestReportStep:
    async def test_operation_code_comes_from_step_not_from_user(self):
        """工序编码来自被点的那一行，用户填的会被覆盖。

        这条是本次改造的核心：改造前「工序编码」是手输文本框，打错不报错。
        """
        svc = _svc()
        with patch.object(ProductionService, "create_report",
                          new_callable=AsyncMock) as create:
            create.return_value = {"id": 1, "step_id": 77}
            await svc.report_step(9, 3, {
                "input_qty": 30, "output_qty": 29, "scrap_qty": 1,
                "operation_code": "ZD999",        # 用户乱填的
                "operation_name": "乱填的名字",
            }, tenant_id="t")

        payload = create.await_args.args[0]
        assert payload["operation_code"] == "CW010", "必须用工序行上的编码"
        assert payload["operation_name"] == "车削"
        assert payload["work_order_id"] == 9
        assert create.await_args.kwargs["step_seq"] == 3

    async def test_missing_step_404_names_the_real_cause(self):
        """工序不存在 → 404，且文案要指出"可能未挂工艺路线"。

        只回"工序不存在"会把排查引向"是不是点错了行"，而真实原因通常是
        这张老单根本没有路线（合法形态）。文案不说，现场会翻很久。
        """
        svc = _svc(step=None)
        with pytest.raises(HTTPException) as ei:
            await svc.report_step(9, 3, {"output_qty": 1}, tenant_id="t")

        assert ei.value.status_code == 404
        msg = ei.value.detail["message"]
        assert "工艺路线" in msg, f"文案没点出真因：{msg}"
        assert "第 3 道" in msg

    async def test_report_date_falls_back_to_business_today(self):
        """没传 report_date 时用 `business_today()`，不是 `date.today()`。"""
        svc = _svc()
        with patch.object(ProductionService, "create_report",
                          new_callable=AsyncMock) as create:
            create.return_value = {"id": 1, "step_id": 77}
            await svc.report_step(9, 3, {"output_qty": 5}, tenant_id="t")

        payload = create.await_args.args[0]
        assert payload["report_date"] == business_today()
        assert isinstance(payload["report_date"], date)

    async def test_explicit_report_date_is_kept(self):
        """补录传了日期就用传的 —— 不能被业务日覆盖成今天。"""
        svc = _svc()
        with patch.object(ProductionService, "create_report",
                          new_callable=AsyncMock) as create:
            create.return_value = {"id": 1, "step_id": 77}
            await svc.report_step(9, 3,
                                  {"output_qty": 5, "report_date": "2026-03-01"},
                                  tenant_id="t")

        payload = create.await_args.args[0]
        assert str(payload["report_date"]).startswith("2026-03-01")

    async def test_caller_dict_is_not_mutated(self):
        """不能原地改调用方传进来的 dict。

        `data["operation_code"] = ...` 直接改的话，调用方（API 层）手里那份
        也被改了；一旦上层复用同一个 dict 做二次处理（比如记日志、重试），
        看到的就不是原始请求了。这类副作用最难查。
        """
        svc = _svc()
        body = {"output_qty": 5, "operation_code": "ZD999"}
        with patch.object(ProductionService, "create_report",
                          new_callable=AsyncMock) as create:
            create.return_value = {"id": 1, "step_id": 77}
            await svc.report_step(9, 3, body, tenant_id="t")

        assert body == {"output_qty": 5, "operation_code": "ZD999"}
        assert "work_order_id" not in body

    async def test_returns_step_id_so_ui_can_confirm(self):
        """返回值要把 `step_id` 透出来 —— 前端据此判断这次报工落到了哪道工序。"""
        svc = _svc()
        with patch.object(ProductionService, "create_report",
                          new_callable=AsyncMock) as create:
            create.return_value = {"id": 5, "step_id": 77}
            out = await svc.report_step(9, 3, {"output_qty": 5}, tenant_id="t")

        assert out["step_id"] == 77
