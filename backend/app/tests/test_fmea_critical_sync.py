"""PFMEA 发布 → 关键工序标记（A+ 外键链）回归测试。

## 被修的是什么

``FmeaService.sync_to_process_route`` 老实现是**必 500**：

    SELECT id FROM route_steps
     WHERE product_id = :pid AND process_name = :pname

这两列在 ``route_steps`` 里都不存在（真实列 ``route_id / operation_id /
step_seq / wc_id / ...``），PG 直接 UndefinedColumn，``get_db`` 整请求回滚。
表现是「PFMEA 只要设了 process_id，点发布就 500」，而多数文档没设
process_id（老代码因此跳过联动），于是这个 500 藏了很久没人撞上。

即使列名蒙对也永远标不上：``fmea_hierarchies.label`` 是自由文本
（实测同一份文档里「压装工序」「压装」并存），``operations.name`` 是标准
词表（「粗车外圆/热处理/外圆磨削」）—— 两套词表，字符串匹配恒 0 条，
**返回体还会显示「已同步 0 个」，看起来像"没有高风险工序"**。

## 新链路

    fmea_hierarchies.operation_id  →  operations.is_critical

route_steps 自带 operation_id，工序被标记后所有引用它的步骤天然继承。

## 这个测试守什么

1. 高风险节点确实把 ``is_critical`` 置真，且**一条 SQL 都不碰 route_steps**；
2. 节点没关联工序时**如实上报跳过数**，不静默 0 条（老实现最要命的那个坑）；
3. 非 PFMEA 文档不动任何数据；
4. 重复发布幂等（只置真、不清零，不会把别人的标记刷掉）；
5. 发布流程**不再依赖 process_id** 才触发联动。
"""
from unittest.mock import patch

from app.services.fmea_service import FmeaService


# ── 替身 ─────────────────────────────────────────────────────

class _FakeSession:
    """OperationRepository 只把它透传，不会真用。"""


class _FakeDocRepo:
    def __init__(self, doc):
        self._doc = doc
        self._session = _FakeSession()   # OperationRepository 会取它做透传
        self.updated: list = []

    async def get_doc(self, doc_id):
        return self._doc

    async def update_doc(self, doc_id, data):
        self.updated.append((doc_id, data))
        self._doc = {**self._doc, **data}
        return 1


class _FakeHierarchyRepo:
    def __init__(self, nodes):
        self._nodes = nodes
        self.tenant_id = None

    def set_tenant_id(self, tid):
        self.tenant_id = tid

    async def list_tree(self, doc_id):
        return list(self._nodes)

    async def get_node(self, node_id):
        return next((n for n in self._nodes if n["id"] == node_id), None)


class _FakeItemRepo:
    def __init__(self, items):
        self._items = items

    async def list_high_risk(self, doc_id, threshold_rpn=100):
        return list(self._items)

    async def list_items(self, doc_id=None, page_size=1000, **kwargs):
        return {"items": list(self._items), "total": len(self._items)}


class _RecordingOpRepo:
    """记录每一条 UPDATE，用来断言"改写哪些工序"和"碰没碰 route_steps"。"""

    instances: list = []

    def __init__(self, session):
        self.session = session
        self.tenant_id = None
        self.statements: list = []
        _RecordingOpRepo.instances.append(self)

    def set_tenant_id(self, tid):
        self.tenant_id = tid

    async def execute(self, sql, params=None):
        self.statements.append((sql, params or {}))
        return 1

    # 断言辅助
    def written_true(self):
        return sorted(
            p["id"] for s, p in self.statements
            if "is_critical = true" in s and "id" in p
        )

    def written_false(self):
        return sorted(
            p["id"] for s, p in self.statements
            if "is_critical = false" in s and "id" in p
        )


def _make_service(doc, nodes, items):
    """绕开 __init__ 里对真仓储的构造 —— 直接装配替身，避免误连本地库。"""
    svc = object.__new__(FmeaService)
    svc.doc_repo = _FakeDocRepo(doc)
    svc.hierarchy_repo = _FakeHierarchyRepo(nodes)
    svc.item_repo = _FakeItemRepo(items)
    svc.action_repo = None
    svc.control_plan_repo = None
    _RecordingOpRepo.instances.clear()
    return svc


def _pfmea_doc(**over):
    doc = {
        "id": 7,
        "tenant_id": "mfg_demo",
        "fmea_type": "PFMEA",
        "process_id": None,          # ★ 故意不设：老代码就靠这个键跳过联动
        "status": "draft",
        "rpn_threshold": 100,
    }
    doc.update(over)
    return doc


# id=1 根节点（不关联工序）、id=2 压装（关联 op 5）、id=3 终检（关联 op 9）
NODES = [
    {"id": 1, "parent_id": None, "level_type": "process", "sort_order": 0,
     "label": "压装工序", "operation_id": None},
    {"id": 2, "parent_id": 1, "level_type": "process_step", "sort_order": 1,
     "label": "压装", "operation_id": 5},
    {"id": 3, "parent_id": 1, "level_type": "process_step", "sort_order": 2,
     "label": "终检", "operation_id": 9},
]

# 只有 id=2 这条被人工标了 is_critical_process
ITEMS = [
    {"id": 101, "hierarchy_id": 2, "is_critical_process": True,
     "rpn": 240, "severity": 9, "occurrence": 6, "detection": 4},
    {"id": 102, "hierarchy_id": 3, "is_critical_process": False,
     "rpn": 168, "severity": 7, "occurrence": 6, "detection": 4},
]


# ── 用例 ─────────────────────────────────────────────────────

async def test_pfmea_marks_critical_operation_and_never_touches_route_steps():
    svc = _make_service(_pfmea_doc(), NODES, ITEMS)
    with patch("app.repositories.basic_data_repo.OperationRepository", _RecordingOpRepo):
        result = await svc.sync_to_process_route(7, "mfg_demo")

    assert result["skipped"] is False
    assert result["critical_operation_ids"] == [5], "只应标记高风险节点上的工序 5"
    assert result["skipped_without_operation"] == 0
    # 未命中的节点 3（op 9）应作为"已被标记但本次不在高风险清单"候选上报
    assert result["stale_operation_ids"] == [9]

    repo = _RecordingOpRepo.instances[-1]
    assert repo.written_true() == [5]
    assert repo.written_false() == [], "只置真、不清零 —— 无权替别的文档清标记"
    # 核心回归：一条 SQL 都不能碰 route_steps（老代码就是打这张表的错列）
    assert not any("route_steps" in s for s, _ in repo.statements)
    # 租户注入要被传下去，否则跨租户写
    assert repo.tenant_id == "mfg_demo"


async def test_node_without_operation_reports_skip_count():
    """节点没关联工序时必须计数上报，不能静默返回 0。"""
    nodes = [
        {"id": 1, "parent_id": None, "level_type": "process", "sort_order": 0,
         "label": "压装工序", "operation_id": None},
    ]
    items = [
        {"id": 101, "hierarchy_id": 1, "is_critical_process": True,
         "rpn": 240, "severity": 9, "occurrence": 6, "detection": 4},
    ]
    svc = _make_service(_pfmea_doc(), nodes, items)
    with patch("app.repositories.basic_data_repo.OperationRepository", _RecordingOpRepo):
        result = await svc.sync_to_process_route(7, "mfg_demo")

    assert result["skipped_without_operation"] == 1
    assert result["critical_operation_ids"] == []
    assert "未关联工序" in result["message"], "必须在文案里说出来，不能只给数字"
    assert _RecordingOpRepo.instances[-1].statements == []


async def test_non_pfmea_does_not_write_anything():
    svc = _make_service(_pfmea_doc(fmea_type="DFMEA"), NODES, ITEMS)
    with patch("app.repositories.basic_data_repo.OperationRepository", _RecordingOpRepo):
        result = await svc.sync_to_process_route(7, "mfg_demo")

    assert result["skipped"] is True
    assert result["critical_operation_ids"] == []
    assert _RecordingOpRepo.instances == [], "非 PFMEA 不该连仓储都不建"


async def test_repeat_publish_is_idempotent():
    """同一份文档连发两次：标记集合不变、只写 true、不写 false。"""
    svc = _make_service(_pfmea_doc(), NODES, ITEMS)
    with patch("app.repositories.basic_data_repo.OperationRepository", _RecordingOpRepo):
        first = await svc.sync_to_process_route(7, "mfg_demo")
        second = await svc.sync_to_process_route(7, "mfg_demo")

    assert first["critical_operation_ids"] == second["critical_operation_ids"] == [5]
    for repo in _RecordingOpRepo.instances:
        assert repo.written_false() == []
        assert repo.written_true() == [5]


async def test_publish_triggers_sync_even_without_process_id():
    """发布流程不能因为没挂工艺路线就不联动 —— 那正是 500 藏住的原因。"""
    items = [
        {"id": 101, "hierarchy_id": 2, "is_critical_process": True,
         "rpn": 240, "severity": 9, "occurrence": 6, "detection": 4,
         "status": "open"},
    ]
    svc = _make_service(_pfmea_doc(process_id=None), NODES, items)

    calls = []

    async def _fake_sync(doc_id, tenant_id):
        calls.append((doc_id, tenant_id))
        return {"message": "已标记 1 个关键工序", "critical_operation_ids": [5]}

    class _NoopControlPlanService:
        def __init__(self, *a, **kw):
            pass

        async def generate_from_fmea(self, doc_id):
            return []

    svc.sync_to_process_route = _fake_sync
    with patch("app.services.fmea_service.ControlPlanService", _NoopControlPlanService):
        result = await svc.publish_document(7)

    assert result["message"] == "发布成功"
    assert calls == [(7, "mfg_demo")], "PFMEA 发布必须触发联动，与 process_id 无关"
    assert result["route_sync"]["critical_operation_ids"] == [5]
