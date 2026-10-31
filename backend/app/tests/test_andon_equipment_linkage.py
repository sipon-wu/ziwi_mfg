"""安灯 ⇄ 设备 ⇄ 工单 联动（台账 B-12 / C-33 / C-34）。

改造前报设备故障只是往 ``andon_call`` 插一行：

    设备台账还是 running  → 大屏上设备"在运行"
    工单还是 in_progress  → 排产以为还在生产
    停机多久无处可查      → OEE 可用率永远算不出来
    恢复后交期纹丝不动    → 停机 2 小时，计划完工一秒都没顺延

安灯于是沦为一块"只会闪的屏"。本文件锁住七条契约：

1. 只有 ``call_type='equipment'`` 且带 ``equipment_id`` 才联动（品质/物料类不误伤）；
2. 报障 → 设备 ``fault`` + 开停机记录 + 工单 ``paused``；
3. 同一设备重复报障复用未关闭的停机记录（否则时长重复累计）；
4. 解决 → 关记录算时长 + 设备 ``running`` + 工单 ``in_progress``；
5. **顺延量必须等于记录的停机时长** —— 两处用不同的数就是"记录说 0 分钟、
   工单却顺延了 0.1 秒"；
6. 停机时长为 0 不改交期（不能平白把交期往后推）；
7. 联动失败不阻断安灯本身成立 —— 报障是既成事实，不能被下游异常回滚。

真实链路验证见 ``e2e/equipment_fault_loop_e2e.py``（A1–A11b，18 段全通）。
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.andon_service import AndonService, _as_dt

CALL = {
    "id": 5,
    "tenant_id": "t1",
    "call_no": "ANDON-1",
    "call_type": "equipment",
    "equipment_id": 13,
    "work_order_id": 101,
    "status": "pending",
}


def _svc():
    """造一个 AndonService，仓储全用 mock（本文件只验行为契约，不验 SQL）。"""
    repo = MagicMock()
    repo._session = MagicMock()
    repo._tenant_id = "t1"
    repo._write_org_id = 3
    return AndonService(repo)


def _fake_prod(order):
    """伪装 ProductionService：``svc.repo`` 挂订单查询，动作打桩。"""
    prod = MagicMock()
    prod.repo = MagicMock()
    prod.repo.get_work_order = AsyncMock(return_value=order)
    prod.repo.update_work_order = AsyncMock(return_value=1)
    prod.pause_work_order = AsyncMock(return_value={"affected": 1})
    prod.resume_work_order = AsyncMock(return_value={"affected": 1})
    return prod


def _patches(tpm=None, dt=None, prod=None):
    """统一打桩三处派生仓储/服务。

    ``AndonService._derived`` 是 ``cls(session)`` 再 inherit_context_from，
    所以 patch 类本身即可（return_value 就是派生出来的那个实例）。

    默认值必须把异步方法都换成 AsyncMock：普通 MagicMock 被 ``await`` 会抛
    TypeError，而联动逻辑是"出错就兜住"，于是测试会得到一条假的
    ``{"error": ...}``，看着像通过、其实什么都没验。
    """
    if tpm is None:
        tpm = MagicMock()
        tpm.update_equipment = AsyncMock(return_value=1)
    if dt is None:
        dt = MagicMock()
        dt.find_open = AsyncMock(return_value=None)
        dt.open_record = AsyncMock(return_value=1)
        dt.close_record = AsyncMock(return_value=1)
    if prod is None:
        prod = _fake_prod(None)
    return (
        patch("app.repositories.tpm_repo.TpmRepository", return_value=tpm),
        patch("app.repositories.tpm_repo.EquipmentDowntimeRepository", return_value=dt),
        patch("app.repositories.production_repo.ProductionRepository",
              return_value=MagicMock()),
        patch("app.services.production_service.ProductionService", return_value=prod),
    )


# ============================================================
# 报障联动
# ============================================================

async def test_non_equipment_call_does_not_link():
    """品质/物料类安灯不该动设备和工单 —— 联动只对设备故障成立。"""
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=6)
    tpm = MagicMock()
    tpm.update_equipment = AsyncMock()
    dt = MagicMock()
    dt.find_open = AsyncMock()

    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt)
    with p1, p2, p3, p4:
        res = await svc.create_call({
            "call_type": "quality", "equipment_id": 13, "work_order_id": 101})

    assert res["linked"] == {}
    tpm.update_equipment.assert_not_awaited()
    dt.find_open.assert_not_awaited()


async def test_call_without_equipment_is_skipped():
    """设备类但没填设备 id：无从联动，也不能抛错。"""
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=7)
    tpm = MagicMock()
    tpm.update_equipment = AsyncMock()

    p1, p2, p3, p4 = _patches(tpm=tpm)
    with p1, p2, p3, p4:
        res = await svc.create_call({"call_type": "equipment", "equipment_id": None})

    assert res["linked"] == {}
    tpm.update_equipment.assert_not_awaited()


async def test_equipment_fault_sets_fault_status():
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=5)
    tpm = MagicMock()
    tpm.update_equipment = AsyncMock(return_value=1)
    dt = MagicMock()
    dt.find_open = AsyncMock(return_value=None)
    dt.open_record = AsyncMock(return_value=3)

    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt, prod=_fake_prod(None))
    with p1, p2, p3, p4:
        res = await svc.create_call(dict(CALL))

    assert res["linked"]["equipment_status"] == "fault"
    assert tpm.update_equipment.await_args.args == (13, {"status": "fault"})


async def test_equipment_fault_opens_downtime():
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=5)
    dt = MagicMock()
    dt.find_open = AsyncMock(return_value=None)
    dt.open_record = AsyncMock(return_value=3)

    p1, p2, p3, p4 = _patches(dt=dt, prod=_fake_prod(None))
    with p1, p2, p3, p4:
        res = await svc.create_call(dict(CALL, description="主轴异响"))

    assert res["linked"]["downtime_id"] == 3
    row = dt.open_record.await_args.args[0]
    assert row["equipment_id"] == 13
    assert row["work_order_id"] == 101
    assert row["andon_call_id"] == 5
    assert row["downtime_type"] == "fault"
    assert row["reason"] == "主轴异响"


async def test_second_call_reuses_open_downtime():
    """连报两次安灯不能开出两条并行停机 —— 时长会被算两遍。"""
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=8)
    dt = MagicMock()
    dt.find_open = AsyncMock(return_value={"id": 3})
    dt.open_record = AsyncMock()

    p1, p2, p3, p4 = _patches(dt=dt, prod=_fake_prod(None))
    with p1, p2, p3, p4:
        res = await svc.create_call(dict(CALL, id=8))

    assert res["linked"]["downtime_id"] == 3
    dt.open_record.assert_not_awaited()


async def test_equipment_fault_pauses_work_order():
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=5)
    dt = MagicMock()
    dt.find_open = AsyncMock(return_value={"id": 3})
    prod = _fake_prod({"id": 101, "wo_status": "in_progress"})

    p1, p2, p3, p4 = _patches(dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc.create_call(dict(CALL))

    assert res["linked"]["work_order_status"] == "paused"
    prod.pause_work_order.assert_awaited_once()


async def test_already_paused_order_is_not_paused_again():
    """已暂停的工单再暂停会撞状态机（in_progress→paused 才合法）。"""
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=5)
    dt = MagicMock()
    dt.find_open = AsyncMock(return_value={"id": 3})
    prod = _fake_prod({"id": 101, "wo_status": "paused"})

    p1, p2, p3, p4 = _patches(dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc.create_call(dict(CALL))

    assert res["linked"]["work_order_status"] == "paused"
    prod.pause_work_order.assert_not_awaited()


async def test_link_failure_does_not_break_call_creation():
    """下游炸了也要兜住 —— 安灯本身必须建成功。"""
    svc = _svc()
    svc.repo.create_call = AsyncMock(return_value=5)
    tpm = MagicMock()
    tpm.update_equipment = AsyncMock(side_effect=RuntimeError("db down"))

    p1, p2, p3, p4 = _patches(tpm=tpm)
    with p1, p2, p3, p4:
        res = await svc.create_call(dict(CALL))

    assert res["id"] == 5
    assert "RuntimeError" in res["linked"]["error"]


# ============================================================
# 解决联动
# ============================================================

def _open_dt(minutes_ago: float):
    started = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {"id": 3, "started_at": started}


def _resolving_svc(minutes_ago: float, wo_status="paused", end_at=None):
    svc = _svc()
    dt = MagicMock()
    dt.find_open = AsyncMock(return_value=_open_dt(minutes_ago))
    dt.close_record = AsyncMock(return_value=1)
    tpm = MagicMock()
    tpm.update_equipment = AsyncMock(return_value=1)
    order = {"id": 101, "wo_status": wo_status,
             "scheduled_end_at": end_at or (datetime.now(timezone.utc) + timedelta(days=1))}
    prod = _fake_prod(order)
    return svc, dt, tpm, prod


async def test_resolve_closes_downtime_with_duration():
    svc, dt, tpm, prod = _resolving_svc(45)
    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve(CALL, "更换轴承", user_id=9)

    dur = res["downtime_minutes"]
    assert 44 <= dur <= 46, dur
    args = dt.close_record.await_args.args
    assert args[0] == 3
    assert args[2] == dur                      # 落库的时长就是返回的时长
    kwargs = dt.close_record.await_args.kwargs
    assert kwargs["resolved_by"] == 9
    assert kwargs["reason"] == "更换轴承"


async def test_resolve_restores_equipment_running():
    svc, dt, tpm, prod = _resolving_svc(10)
    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve(CALL, "已修复")

    assert res["equipment_status"] == "running"
    assert tpm.update_equipment.await_args.args == (13, {"status": "running"})


async def test_resolve_resumes_work_order():
    svc, dt, tpm, prod = _resolving_svc(10)
    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve(CALL, "已修复")

    assert res["work_order_status"] == "in_progress"
    prod.resume_work_order.assert_awaited_once()


async def test_resolve_reschedules_end_by_exact_downtime():
    """★ 顺延量必须**精确等于**记录的停机时长。

    如果两处取整方式不同，就会出现"停机记录写 90 分钟、交期却顺延 90.4 分钟"，
    或者更糟的"记录 0 分钟、交期顺延了 0.1 秒"—— 排产表从此不可信。
    """
    end0 = datetime.now(timezone.utc) + timedelta(days=1)
    svc, dt, tpm, prod = _resolving_svc(90, end_at=end0)
    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve(CALL, "已修复")

    minutes = res["downtime_minutes"]
    assert 89 <= minutes <= 91, minutes

    new_end = prod.repo.update_work_order.await_args.args[1]["scheduled_end_at"]
    delta = (_as_dt(new_end) - _as_dt(end0)).total_seconds() / 60.0
    assert abs(delta - minutes) < 1e-6, f"顺延 {delta} != 停机 {minutes}"
    assert _as_dt(res["rescheduled_end_at"]) == _as_dt(new_end)


async def test_zero_minute_downtime_does_not_reschedule():
    """停机 0 分钟（秒级抖动）不该动交期 —— 平白推后交期同样是错。"""
    svc, dt, tpm, prod = _resolving_svc(0)
    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve(CALL, "虚惊一场")

    assert res["downtime_minutes"] == 0.0
    prod.repo.update_work_order.assert_not_awaited()
    assert "rescheduled_end_at" not in res


async def test_not_paused_order_is_not_resumed():
    """故障期间工单没被暂停（比如已完工），解决时不能硬恢复。"""
    svc, dt, tpm, prod = _resolving_svc(10, wo_status="completed")
    p1, p2, p3, p4 = _patches(tpm=tpm, dt=dt, prod=prod)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve(CALL, "已修复")

    prod.resume_work_order.assert_not_awaited()
    assert "work_order_status" not in res


async def test_resolve_without_equipment_is_noop():
    svc = _svc()
    tpm = MagicMock()
    tpm.update_equipment = AsyncMock()
    p1, p2, p3, p4 = _patches(tpm=tpm)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve({"id": 1, "call_type": "quality"}, "x")
    assert res == {}
    tpm.update_equipment.assert_not_awaited()


async def test_resolve_failure_does_not_raise():
    svc = _svc()
    tpm = MagicMock()
    tpm.update_equipment = AsyncMock(side_effect=RuntimeError("db down"))
    p1, p2, p3, p4 = _patches(tpm=tpm)
    with p1, p2, p3, p4:
        res = await svc._link_on_resolve(CALL, "已修复")
    assert "RuntimeError" in res["error"]


# ============================================================
# 接线检查：入口真的调了 service
# ============================================================

async def test_update_call_status_resolved_triggers_restore():
    """★ 接线检查：resolve 走的必须是 service 的恢复逻辑，不是裸 update。

    只测 ``_link_on_resolve`` 本身不够 —— 方法写对了但 API 还直连
    ``repo.update_call_status``，缺陷照旧存在（本项目已踩过多次
    "实现有了、入口没接"）。
    """
    svc = _svc()
    svc.repo.update_call_status = AsyncMock(return_value=1)
    svc.repo.get_call = AsyncMock(return_value=dict(CALL))
    with patch.object(svc, "_link_on_resolve", new_callable=AsyncMock,
                      return_value={"equipment_status": "running"}) as mocked:
        res = await svc.update_call_status(5, "resolved", {"resolution": "ok"})

    mocked.assert_awaited_once()
    assert res["restored"]["equipment_status"] == "running"


async def test_update_call_status_ack_does_not_restore():
    """确认（acknowledged）不是解决，不该触发恢复与重排。"""
    svc = _svc()
    svc.repo.update_call_status = AsyncMock(return_value=1)
    with patch.object(svc, "_link_on_resolve", new_callable=AsyncMock) as mocked:
        await svc.update_call_status(5, "acknowledged", {})

    svc.repo.get_call.assert_not_called()
    mocked.assert_not_awaited()
