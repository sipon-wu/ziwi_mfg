"""AI Copilot（E1）API 端到端测试。

使用**真实 SQLite 库**（子集建表 + 显式主键种子）验证：
- 问数返回**真实数值 + 来源脚注**；
- 写意图被拒（只读护栏 R1）；
- 无数据返回固定话术（零臆造 R3）；
- 租户隔离（换 tenant 拿不到别家数据，R2）；
- 数据源不可用指标返回「暂不可用」而非报错/编造；
- 复合问句 / 角色简报 / 反馈 / 会话列表。

说明：SQLite 的 BIGINT 主键不自增，业务表种子统一显式指定 id（与项目既有做法一致）。
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.andon import AndonCall
from app.models.copilot import (
    CopilotAskLog,
    CopilotDocChunk,
    CopilotFeedback,
    CopilotMessage,
    CopilotSession,
    MetricDefinition,
)
from app.models.production import WorkOrder, WorkReport
from app.models.role import Role
from app.models.tpm import Equipment, MaintenancePlan, MaintenanceTask

_TABLES = [
    WorkOrder.__table__,
    WorkReport.__table__,
    CopilotSession.__table__,
    CopilotMessage.__table__,
    CopilotFeedback.__table__,
    CopilotAskLog.__table__,
    MetricDefinition.__table__,
    CopilotDocChunk.__table__,
    Role.__table__,
    AndonCall.__table__,
    Equipment.__table__,
    MaintenanceTask.__table__,
    MaintenancePlan.__table__,
]

_TZ = timedelta(hours=8)


def _parse_sse(body: str) -> list:
    """把 SSE 文本解析为事件 dict 列表。"""
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                events.append(json.loads(payload))
            except Exception:
                continue
    return events


def _find(events: list, etype: str):
    for ev in events:
        if ev.get("type") == etype:
            return ev
    return None


class _Env:
    """测试环境单例（engine + 当前租户）。"""

    engine = None
    tenant = "default"


@pytest.fixture
async def env():
    """创建 SQLite 库、种子数据、安装依赖覆盖，返回 AsyncClient。"""
    fp = os.path.join(tempfile.gettempdir(), f"copilot_test_{os.getpid()}_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{fp}")
    _Env.engine = engine
    _Env.tenant = "default"

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))

    today = (datetime.now() + _TZ).date()
    yesterday = today - timedelta(days=1)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        # 工单（显式 id）
        await s.execute(
            text(
                "INSERT INTO work_orders (id, tenant_id, wo_no, wo_status, product_code, product_name, "
                "planned_qty, completed_qty, scrap_qty, workshop, line_code, created_at) VALUES "
                "(1,'default','WO-D1','completed','P1','产品1',100,100,5,'一号车间','L3',:t)"
            ),
            {"t": datetime.now()},
        )
        # default 租户：昨天 产出 100 / 不良 5
        await s.execute(
            text(
                "INSERT INTO work_reports (id, tenant_id, work_order_id, report_date, reporter_id, "
                "operation_code, output_qty, scrap_qty, labor_hours, machine_hours, status) VALUES "
                "(1,'default',1,:d,1,'OP1',100,5,8.0,4.0,'submitted')"
            ),
            {"d": yesterday.isoformat()},
        )
        # other 租户：昨天 产出 999（用于验证租户隔离，绝不能泄漏给 default）
        await s.execute(
            text(
                "INSERT INTO work_reports (id, tenant_id, work_order_id, report_date, reporter_id, "
                "operation_code, output_qty, scrap_qty, labor_hours, machine_hours, status) VALUES "
                "(2,'other',1,:d,1,'OP1',999,0,0,0,'submitted')"
            ),
            {"d": yesterday.isoformat()},
        )
        # 上月数据（default）：用于「本月」无数据场景不影响
        # 安灯：今天一条未闭环
        await s.execute(
            text(
                "INSERT INTO andon_call (id, tenant_id, call_no, call_type, caller_id, description, "
                "priority, status, created_at) VALUES "
                "(1,'default','AD1','equipment',1,'设备故障','high','pending',:t)"
            ),
            {"t": datetime.now()},
        )
        await s.commit()

    async def _get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _get_user():
        return {"id": 1, "username": "tester", "tenant_id": _Env.tenant, "role_id": 1}

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    await engine.dispose()
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except OSError:
            pass


async def _ask(client, question: str, session_id=None):
    body = {"question": question}
    if session_id is not None:
        body["session_id"] = session_id
    resp = await client.post("/api/v1/copilot/ask", json=body)
    assert resp.status_code == 200
    return _parse_sse(resp.text)


class TestCopilotAsk:
    """主链路问数。"""

    async def test_output_yesterday_real_number_and_footnote(self, env):
        """昨天产量 → 真实数值 100 + 来源脚注。"""
        events = await _ask(env, "昨天产量是多少")
        answer = _find(events, "answer")
        assert answer is not None, events
        payload = answer["payload"]
        assert payload["answered"] is True
        assert payload["data"]["value"] == 100
        assert "100" in payload["narrative"]
        # 来源脚注强制存在
        assert payload["source"] is not None
        assert "work_reports" in payload["source"]["table_or_caliber"]
        assert payload["source"]["record_count"] >= 1

    async def test_write_intent_rejected(self, env):
        """写意图 → 只读护栏拒绝。"""
        events = await _ask(env, "帮我创建一个新的工单")
        reject = _find(events, "reject")
        assert reject is not None, events
        assert reject["reason"] == "write_intent"
        answer = _find(events, "answer")
        assert answer["payload"]["answered"] is False

    async def test_no_data_fixed_phrasing(self, env):
        """上周产量（无种子）→ 固定无数据话术，不编造。"""
        events = await _ask(env, "上周的产量是多少")
        answer = _find(events, "answer")
        payload = answer["payload"]
        assert payload["data"]["value"] is None or payload["answered"] is False
        # 绝不出现臆造数字
        assert "未查询到" in payload["narrative"] or "无数据" in payload["narrative"]

    async def test_tenant_isolation(self, env):
        """换租户 → 拿到自己的数值（999），拿不到别家（100）。"""
        _Env.tenant = "other"
        events = await _ask(env, "昨天产量是多少")
        answer = _find(events, "answer")
        payload = answer["payload"]
        assert payload["data"]["value"] == 999
        assert "100" not in json.dumps(payload["data"], ensure_ascii=False)

    async def test_unavailable_metric(self, env):
        """设备停机时长（无数据源）→ 明确「暂不可用」，不报错、不编造。"""
        events = await _ask(env, "哪台设备本月停机时间最长")
        answer = _find(events, "answer")
        payload = answer["payload"]
        assert payload["answered"] is False
        assert payload["data"]["available"] is False
        assert "暂不可用" in payload["narrative"]
        assert "未报表" in payload["narrative"] or "数据源" in payload["narrative"]

    async def test_grouped_dimension(self, env):
        """按产线分组 → 表格/图表维度数据。"""
        events = await _ask(env, "昨天各产线产量")
        answer = _find(events, "answer")
        payload = answer["payload"]
        assert payload["data"]["value"] is None or isinstance(payload["data"]["rows"], list)
        assert len(payload["data"]["rows"]) >= 1

    async def test_composite_summary_marks_unavailable(self, env):
        """复合问句（产量良率OEE汇总）→ 汇总卡，OEE 标注不可用。"""
        events = await _ask(env, "今天产量良率OEE汇总")
        answer = _find(events, "answer")
        payload = answer["payload"]
        cards = payload["data"].get("cards", [])
        assert cards, payload
        oee = next((c for c in cards if c["metric_code"] == "oee"), None)
        assert oee is not None and oee["available"] is False

    async def test_multi_turn_session(self, env):
        """多轮上下文：同一 session 追问继承指标。"""
        events1 = await _ask(env, "昨天产量是多少")
        session_ev = _find(events1, "session")
        sid = session_ev["session_id"]
        # 第二个问题用不同会话则不继承；这里仅验证 session 可复用且返回数值
        events2 = await _ask(env, "昨天产量是多少", session_id=sid)
        answer = _find(events2, "answer")
        assert answer["payload"]["data"]["value"] == 100


class TestCopilotBriefing:
    """角色简报 / 反馈 / 会话。"""

    async def test_briefing_factory(self, env):
        resp = await env.post("/api/v1/copilot/briefing", json={"role": "厂长"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        cards = data["data"]["cards"]
        assert cards
        # OEE 卡片应标注不可用，且不编造数值
        oee = next((c for c in cards if c["metric_code"] == "oee"), None)
        assert oee is not None and oee["available"] is False

    async def test_briefing_all_roles(self, env):
        for role in ("厂长", "质量", "设备", "车间主任"):
            resp = await env.post("/api/v1/copilot/briefing", json={"role": role})
            assert resp.status_code == 200
            assert resp.json()["data"]["cards"]

    async def test_feedback(self, env):
        resp = await env.post("/api/v1/copilot/feedback", json={"message_id": 1, "rating": "good"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_feedback_bad_rating(self, env):
        resp = await env.post("/api/v1/copilot/feedback", json={"message_id": 1, "rating": "meh"})
        assert resp.status_code == 400

    async def test_sessions_list_and_delete(self, env):
        # 先问一次产生会话
        await _ask(env, "昨天产量是多少")
        resp = await env.get("/api/v1/copilot/sessions")
        assert resp.status_code == 200
        sessions = resp.json()["data"]
        assert len(sessions) >= 1
        sid = sessions[0]["id"]
        resp2 = await env.delete(f"/api/v1/copilot/sessions/{sid}")
        assert resp2.status_code == 200
        assert resp2.json()["code"] == 0
