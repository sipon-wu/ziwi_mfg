#!/usr/bin/env python3
"""AI Copilot（E1）端到端联调烟测（runnable，无需外部服务）。

在进程内用真实 SQLite 库 + ASGI 传输跑通「只读问数」四大边界，作为可复现证据：

    ① 问数返回**真实数值 + 来源脚注**（如「昨天产量」）
    ② **写意图被拒**（只读护栏 R1）
    ③ **无数据**返回固定话术（零臆造 R3）
    ④ **租户隔离**（换 tenant 拿不到别家数据 R2）
    ⑤ 数据源不可用指标 → 「暂不可用」（非报错、非编造）

用法：
    backend/.venv/Scripts/python.exe e2e/copilot_smoke.py
退出码 0 = 全部通过；非 0 = 存在失败项。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from datetime import timedelta

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(CODE_ROOT, "backend")
for p in (BACKEND_DIR,):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("AI_GATEWAY_ENABLED", "false")  # 走规则降级链路，保证可演示

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.core.business_time import business_now  # noqa: E402
from app.models.copilot import (  # noqa: E402
    CopilotAskLog,
    CopilotDocChunk,
    CopilotFeedback,
    CopilotMessage,
    CopilotSession,
    MetricDefinition,
)
from app.models.production import WorkOrder, WorkReport  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.user import UserOrganization, UserRole  # noqa: E402
from app.models.andon import AndonCall  # noqa: E402
from app.models.tpm import Equipment, MaintenancePlan, MaintenanceTask  # noqa: E402

_CURRENT_TENANT = {"id": "default"}
_RESULTS: list = []


def _parse_sse(body: str) -> list:
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except Exception:
                    pass
    return events


def _find(events: list, etype: str):
    return next((e for e in events if e.get("type") == etype), None)


def _check(name: str, ok: bool, detail: str = "") -> None:
    _RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    tables = [
        WorkOrder.__table__, WorkReport.__table__, CopilotSession.__table__,
        CopilotMessage.__table__, CopilotFeedback.__table__, CopilotAskLog.__table__,
        MetricDefinition.__table__, CopilotDocChunk.__table__, Role.__table__,
        # ★ `user_roles` 必须显式列出：它是 `User.roles` 的 secondary 关联表，
        #   没有对应的映射类，只给 `Role.__table__` 建不出它。
        #   漏了它的后果是：每个请求的 `get_user_roles()` 都抛
        #   `sqlite3.OperationalError: no such table: user_roles` —— 这条异常在
        #   数据范围解析里被兜底吞掉，原先"看起来无事"；改成 fail-closed 并
        #   logger.exception 之后，堆栈打上 stderr，run_all 的 ERROR 探测把它判成
        #   探针失败。**静默兜底会掩盖环境缺陷，日志会把它翻出来** —— 这次是好事。
        UserRole.__table__,
        # 同理 `user_organizations`：数据范围解析要按它取"我属于哪些组织"，
        # 缺表 → 每个请求一条 no such table。**建表清单要跟着鉴权链路走**，
        # 只列业务表是不够的。
        UserOrganization.__table__,
        AndonCall.__table__, Equipment.__table__, MaintenancePlan.__table__, MaintenanceTask.__table__,
    ]
    fp = os.path.join(tempfile.gettempdir(), f"copilot_e2e_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{fp}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    # 时间基准与服务端**同源**（MetricQueryService._today() 就是 business_today()）：
    # 直接调 business_now() 取 naive 值，不在探针里自己再算一份偏移 ——
    # 曾经这里写死 timedelta(hours=8)，业务偏移一改，探针与实现就各走一套基准，
    # 跑出来的红是假的、绿也是假的。
    today = business_now().replace(tzinfo=None).date()
    yesterday = today - timedelta(days=1)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text(
            "INSERT INTO work_orders (id, tenant_id, wo_no, wo_status, product_code, product_name, "
            "planned_qty, completed_qty, scrap_qty, workshop, line_code) VALUES "
            "(1,'default','WO-D1','completed','P1','产品1',100,100,5,'一号车间','L3')"))
        await s.execute(text(
            "INSERT INTO work_reports (id, tenant_id, work_order_id, report_date, reporter_id, "
            "operation_code, output_qty, scrap_qty, status) VALUES (1,'default',1,:d,1,'OP1',100,5,'submitted')"),
            {"d": yesterday.isoformat()})
        await s.execute(text(
            "INSERT INTO work_reports (id, tenant_id, work_order_id, report_date, reporter_id, "
            "operation_code, output_qty, scrap_qty, status) VALUES (2,'other',1,:d,1,'OP1',999,0,'submitted')"),
            {"d": yesterday.isoformat()})
        await s.commit()

    async def _db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _user():
        return {"id": 1, "username": "e2e", "tenant_id": _CURRENT_TENANT["id"], "role_id": 1}

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://copilot.local") as cl:
        async def ask(q):
            r = await cl.post("/api/v1/copilot/ask", json={"question": q})
            return _parse_sse(r.text)

        # ① 真实数值 + 来源脚注
        ev = await ask("昨天产量是多少")
        ans = _find(ev, "answer")
        payload = ans["payload"] if ans else {}
        ok = (payload.get("data", {}).get("value") == 100
              and payload.get("source", {}).get("table_or_caliber", "").find("work_reports") >= 0)
        _check("① 昨天产量=真实值100 且含来源脚注", ok,
               f"value={payload.get('data',{}).get('value')} source={payload.get('source',{}).get('table_or_caliber')}")

        # ② 写意图被拒
        ev = await ask("帮我创建一个新的工单")
        rej = _find(ev, "reject")
        _check("② 写意图被拒", bool(rej) and rej.get("reason") == "write_intent",
               f"reason={rej.get('reason') if rej else None}")

        # ③ 无数据固定话术
        #
        # ★ 判据不能用「上周有没有数据」：fixture 的报工记在「昨天」，而「昨天」
        #   是否落在「上周」取决于今天是周几 —— 每到**周一**，昨天（周日）就落进
        #   「上周」，这条断言在周一必然翻红。2026-11-09 00:0x 实测踩到：同一份代码
        #   周日晚还是 6/6 全绿，跨过零点变 5/6，而这一晚没有任何代码变更。
        #   同理「本月」在每月 1 号、「今天」在 fixture 换日时都会翻。
        #   所以改成切到一个**一定没有数据**的租户：要验的是"没数据时不许编"，
        #   与周几、日历、跑在几点都无关。租户 id 用随机串，不依赖任何别处的 fixture。
        _CURRENT_TENANT["id"] = f"copilot-empty-{uuid.uuid4().hex[:8]}"
        ev = await ask("上周产量是多少")
        ans = _find(ev, "answer")
        narrative = ans["payload"]["narrative"] if ans else ""
        _check("③ 无数据返回固定话术（零臆造）", "未查询到" in narrative, narrative[:40])
        _CURRENT_TENANT["id"] = "default"

        # ④ 租户隔离
        _CURRENT_TENANT["id"] = "other"
        ev = await ask("昨天产量是多少")
        ans = _find(ev, "answer")
        val_other = ans["payload"]["data"]["value"] if ans else None
        leaked = "100" in json.dumps(ans["payload"]["data"], ensure_ascii=False) if ans else True
        _check("④ 租户隔离（other 拿到 999，不含 default 的 100）", val_other == 999 and not leaked,
               f"value={val_other}")
        _CURRENT_TENANT["id"] = "default"

        # ⑤ 数据源不可用
        ev = await ask("哪台设备本月停机时间最长")
        ans = _find(ev, "answer")
        p5 = ans["payload"] if ans else {}
        _check("⑤ 停机时长→暂不可用（不报错、不编造）",
               p5.get("answered") is False and "暂不可用" in p5.get("narrative", ""),
               p5.get("narrative", "")[:40])

        # ⑥ 角色简报
        r = await cl.post("/api/v1/copilot/briefing", json={"role": "厂长"})
        j = r.json()
        _check("⑥ 角色简报可生成", r.status_code == 200 and len(j["data"]["cards"]) > 0,
               f"cards={len(j['data']['cards'])}")

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    await engine.dispose()
    try:
        os.remove(fp)
    except OSError:
        pass

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print(f"\n=== 端到端烟测：{passed}/{total} 通过 ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
