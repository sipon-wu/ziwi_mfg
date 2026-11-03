"""控制计划自动生成：必填绑定参数回归测试。

## 被修的是什么

``ControlPlanService.generate_from_fmea`` 组 ``cp_data`` 时只给了 9 个字段，
而 ``ControlPlanRepository.create_control_plan`` 的 INSERT 硬编码了 11 个
**命名占位符**：

    INSERT INTO control_plans (..., source, status)
    VALUES (..., :source, :status)

原生 SQL 下，占位符在编译阶段就要求绑定，少一个直接：

    StatementError: A value is required for bind parameter 'source'

``ControlPlan.source`` 上写的 ``default="auto"`` 是 **ORM 层**的 Python 默认，
只对 "Python 侧 INSERT 且未提供该列" 生效，救不了手写 SQL。

后果（推进器厂 M10 场景实测）：

- ``POST /fmea/control-plans/generate`` 100% 500 → 控制计划一条也生不出来
- ``POST /fmea/documents/{id}/publish`` 100% 500 —— 发布流程末尾会顺带生成
  控制计划，PFMEA 永远发不出去，质量体系卡在"草稿"

## 这个测试守的是什么

守的是**"service 组的 dict 必须覆盖 repo SQL 里所有占位符"**这条契约 ——
它是跨文件的、编译期才炸的，只靠跑通其它用例发现不了。
"""
from app.services.control_plan_service import ControlPlanService


class _FakePlanRepo:
    """ControlPlanRepository 的最小替身：只记录被写进去的 dict。"""

    def __init__(self, tenant_id: str = "mfg_demo"):
        self.tenant_id = tenant_id
        self._session = object()          # ControlPlanService 只透传，不用
        self.deleted: list = []
        self.created: list = []

    async def delete_by_fmea_doc(self, fmea_doc_id: int) -> int:
        self.deleted.append(fmea_doc_id)
        return 1

    async def create_control_plan(self, data: dict) -> int:
        self.created.append(data)
        return len(self.created)


class _StubItemRepo:
    def __init__(self, items: list):
        self._items = items

    async def list_items(self, doc_id=None, page_size=1000, **kwargs):
        return {"items": self._items, "total": len(self._items)}


HIGH_RISK_ITEM = {
    "id": 11,
    "failure_mode": "压装不到位",
    "current_control_prevent": "首件抽检",
    "current_control_detect": "下线气隙测量",
    "function_desc": "压装到位",
    "is_high_risk": True,
    "severity": 9,
}


async def test_generate_fills_source_and_status():
    """SQL 里的 source / status 占位符必须有值可绑，否则发布直接 500。"""
    repo = _FakePlanRepo()
    svc = ControlPlanService(repo)
    svc.item_repo = _StubItemRepo([HIGH_RISK_ITEM])

    count = await svc.generate_from_fmea(6, "mfg_demo")

    assert count == 1
    assert repo.deleted == [6], "重新生成前必须先清掉旧的自动计划"
    row = repo.created[0]
    assert row.get("source") == "auto", "source 缺失 → StatementError"
    assert row.get("status") == "draft", "status 缺失 → StatementError"
    assert row.get("tenant_id") == "mfg_demo"


async def test_generate_skips_when_no_high_risk_item():
    """没有高风险项时返回 0，且不该把已有的控制计划清空。

    清空动作放在"确认有料"之后，否则一次空跑会把人工维护过的计划一起删掉。
    """
    repo = _FakePlanRepo()
    svc = ControlPlanService(repo)
    svc.item_repo = _StubItemRepo([{**HIGH_RISK_ITEM, "is_high_risk": False}])

    count = await svc.generate_from_fmea(7, "mfg_demo")

    assert count == 0
    assert repo.deleted == []
    assert repo.created == []
