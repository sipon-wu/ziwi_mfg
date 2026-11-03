"""M12 数据采集 · 场景验收探针（推进器厂：伺服压机压力/扭矩直采）。

## 这个探针要回答什么

覆盖矩阵显示 M12 只有 **3/23** 条路由被任何探针碰过（13%），而 A推进器厂方案书
§3.3 有 **42 行采集要求**（设备/核心采集数据/采集方式）。此前场景验证报告据此写成
"G4 数据采集：平台没有网关端点" —— 但把路由静态导出来看，`POST /collect/iot/ingest`
和 `/collect/iot/ingest-batch` **都在**，23 条路由一条不缺。

所以 G4 的真实状态不是"平台没有"，而是**"通道建好了没人接过、也没验过"**。
这个探针就是把这条通道从建网关 → 建数据源 → 建设备 → 建采集任务 → 推数 → 查数
整条走一遍，用真实压力值验证落库。

## 场景

伺服压机压装工序（方案书工序 CW020 / 采集项：压力 MPa、位移 mm）。
一台网关带两台设备，按 Modbus 寄存器映射到 `pressure` / `displacement` 两个测点。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/collect_iot_e2e.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("TENANT_CODE", "MFG1")
USER = os.environ.get("ADMIN_USER", "mfg_admin")
PWD = os.environ.get("ADMIN_PWD", "admin123")

PASS = FAIL = 0
FAILS: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}")
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))
    return ok


def data(r: httpx.Response):
    try:
        return (r.json() or {}).get("data")
    except Exception:
        return None


def items(r: httpx.Response) -> list:
    d = data(r)
    if isinstance(d, dict):
        return d.get("items") or []
    return d or []


def msg(r: httpx.Response) -> str:
    try:
        return str(r.json().get("message") or r.text)[:160]
    except Exception:
        return r.text[:160]


def login(c: httpx.Client) -> dict:
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_code": TENANT})
    r.raise_for_status()
    body = r.json()
    # 登录接口不套 {"code","data"} 外层，token 直接在顶层；
    # 但其它接口一律套 data —— 这里两种形状都接住，避免"登录成功却被判失败"。
    payload = body.get("data") if isinstance(body.get("data"), dict) else body
    tok = payload.get("access_token")
    if not tok:
        print("登录失败：", r.text[:300])
        sys.exit(1)
    c.headers["Authorization"] = f"Bearer {tok}"
    if not payload.get("tenant_id"):
        me = c.get(f"{API}/auth/me")
        payload = {**payload, **(data(me) or {})}
    return payload


def main() -> int:
    tag = datetime.now().strftime("%m%d%H%M%S")
    c = httpx.Client(timeout=25)
    info = login(c)
    print(f"登录成功 tenant={info.get('tenant_id')} tag={tag}\n")

    print("=" * 62)
    print("M12 数据采集 · 推进器厂伺服压机直采")
    print("=" * 62)

    # ── S1 网关 ────────────────────────────────────────────────
    print("\n── S1 IoT 网关 ──")
    r = c.post(f"{API}/collect/gateways", json={
        "gateway_code": f"GW-{tag}", "gateway_name": f"总装车间网关{tag}",
        "gateway_type": "edge", "ip_address": "192.168.10.21",
        "firmware_version": "v2.3.1", "location": "总装车间-压装工位",
        "mqtt_topic_prefix": f"ziwi/{tag}"})
    gw_id = (data(r) or {}).get("id")
    report("S1-1 网关可创建", r.status_code == 200 and bool(gw_id),
           f"HTTP {r.status_code} id={gw_id} {msg(r) if not gw_id else ''}")
    if not gw_id:
        print("\n网关建不出来，后续无法继续。")
        return finish()

    r = c.get(f"{API}/collect/gateways", params={"page_size": 100})
    rows = items(r)
    hit = next((g for g in rows if g.get("id") == gw_id), None)
    report("S1-2 网关出现在列表", r.status_code == 200 and bool(hit),
           f"HTTP {r.status_code} 共 {len(rows)} 台")
    report("S1-3 网关字段完整（IP/固件/MQTT 前缀）",
           bool(hit) and hit.get("ip_address") == "192.168.10.21"
           and hit.get("firmware_version") == "v2.3.1"
           and hit.get("mqtt_topic_prefix") == f"ziwi/{tag}",
           f"{hit.get('ip_address') if hit else None} / {hit.get('firmware_version') if hit else None}")

    r = c.get(f"{API}/collect/gateways/{gw_id}")
    report("S1-4 网关详情可查", r.status_code == 200
           and (data(r) or {}).get("id") == gw_id)

    # ── S2 数据源 ──────────────────────────────────────────────
    print("\n── S2 数据源配置 ──")
    r = c.post(f"{API}/collect/data-sources", json={
        "source_name": f"压机OPCUA{tag}", "source_type": "opcua",
        "source_code": f"DS-{tag}", "protocol": "OPC-UA",
        "connection_info": {"endpoint": "opc.tcp://192.168.10.21:4840",
                            "security": "None"},
        "gateway_id": gw_id, "factory_id": "THR-A"})
    ds_id = (data(r) or {}).get("id")
    report("S2-1 数据源可创建", r.status_code == 200 and bool(ds_id),
           f"HTTP {r.status_code} id={ds_id} {msg(r) if not ds_id else ''}")

    r = c.get(f"{API}/collect/data-sources", params={"page_size": 100})
    rows = items(r)
    report("S2-2 数据源出现在列表",
           any(x.get("id") == ds_id for x in rows), f"共 {len(rows)} 个")

    r = c.get(f"{API}/collect/data-sources", params={"source_type": "opcua", "page_size": 100})
    rows = items(r)
    report("S2-3 按 source_type 过滤生效",
           all(x.get("source_type") == "opcua" for x in rows) and len(rows) >= 1,
           f"opcua {len(rows)} 个")

    r = c.get(f"{API}/collect/data-sources/{ds_id}")
    ds = data(r) or {}
    report("S2-4 数据源详情可查", r.status_code == 200 and ds.get("id") == ds_id)
    report("S2-5 connection_info 原样存取",
           (ds.get("connection_info") or {}).get("endpoint") == "opc.tcp://192.168.10.21:4840",
           str(ds.get("connection_info"))[:80])

    r = c.put(f"{API}/collect/data-sources/{ds_id}", json={"is_active": False})
    r2 = c.get(f"{API}/collect/data-sources/{ds_id}")
    report("S2-6 数据源可停用", r.status_code == 200
           and (data(r2) or {}).get("is_active") in (False, 0))
    c.put(f"{API}/collect/data-sources/{ds_id}", json={"is_active": True})

    # 单独建一个用来验证删除
    r = c.post(f"{API}/collect/data-sources", json={
        "source_name": f"待删数据源{tag}", "source_type": "modbus",
        "source_code": f"DS-DEL-{tag}", "protocol": "Modbus-TCP"})
    del_id = (data(r) or {}).get("id")
    r = c.delete(f"{API}/collect/data-sources/{del_id}")
    r2 = c.get(f"{API}/collect/data-sources/{del_id}")
    report("S2-7 数据源可删除（删除后查不到）",
           r.status_code == 200 and r2.status_code == 404,
           f"DEL {r.status_code} / GET {r2.status_code}")

    # ── S3 IoT 设备 ────────────────────────────────────────────
    print("\n── S3 IoT 设备（伺服压机）──")
    r = c.post(f"{API}/collect/devices", json={
        "gateway_id": gw_id, "device_code": f"PRS-{tag}",
        "device_name": f"伺服压机{tag}", "device_type": "press",
        "protocol": "Modbus-TCP", "register_address": "40001",
        "data_type": "float", "unit": "MPa", "location": "压装工位-1"})
    dev_id = (data(r) or {}).get("id")
    report("S3-1 IoT 设备可注册", r.status_code == 200 and bool(dev_id),
           f"HTTP {r.status_code} id={dev_id} {msg(r) if not dev_id else ''}")

    r = c.get(f"{API}/collect/devices", params={"gateway_id": gw_id, "page_size": 100})
    rows = items(r)
    report("S3-2 设备挂在指定网关下",
           any(x.get("id") == dev_id for x in rows), f"该网关 {len(rows)} 台")
    hit = next((x for x in rows if x.get("id") == dev_id), {})
    report("S3-3 寄存器映射与单位落库",
           hit.get("register_address") == "40001" and hit.get("unit") == "MPa",
           f"{hit.get('register_address')} / {hit.get('unit')}")

    # ── S4 采集任务 ────────────────────────────────────────────
    print("\n── S4 采集任务 ──")
    r = c.post(f"{API}/collect/tasks", json={
        "task_no": f"CT-{tag}", "task_name": f"压装压力采集{tag}",
        "source_id": ds_id, "collect_interval_seconds": 5,
        "collect_fields": [{"point": "pressure", "unit": "MPa"},
                           {"point": "displacement", "unit": "mm"}],
        "device_id": dev_id, "factory_id": "THR-A"})
    task_id = (data(r) or {}).get("id")
    report("S4-1 采集任务可创建", r.status_code == 200 and bool(task_id),
           f"HTTP {r.status_code} id={task_id} {msg(r) if not task_id else ''}")

    r = c.get(f"{API}/collect/tasks", params={"page_size": 100})
    rows = items(r)
    task = next((t for t in rows if t.get("id") == task_id), {})
    report("S4-2 任务出现在列表", bool(task), f"共 {len(rows)} 个")
    report("S4-3 任务挂上数据源与设备",
           task.get("source_id") == ds_id and task.get("device_id") == dev_id,
           f"source={task.get('source_id')} device={task.get('device_id')}")

    r = c.get(f"{API}/collect/tasks/{task_id}")
    report("S4-4 任务详情可查", r.status_code == 200
           and (data(r) or {}).get("task_no") == f"CT-{tag}")

    r = c.put(f"{API}/collect/tasks/{task_id}",
              json={"collect_interval_seconds": 30, "is_active": False})
    r2 = c.get(f"{API}/collect/tasks/{task_id}")
    t2 = data(r2) or {}
    report("S4-5 任务可改周期并停用",
           r.status_code == 200 and t2.get("collect_interval_seconds") == 30
           and t2.get("is_active") in (False, 0),
           f"interval={t2.get('collect_interval_seconds')} active={t2.get('is_active')}")
    c.put(f"{API}/collect/tasks/{task_id}", json={"is_active": True})

    # 删除验证
    r = c.post(f"{API}/collect/tasks", json={
        "task_no": f"CT-DEL-{tag}", "task_name": "待删任务",
        "source_id": ds_id, "collect_interval_seconds": 60})
    del_task = (data(r) or {}).get("id")
    r = c.delete(f"{API}/collect/tasks/{del_task}")
    r2 = c.get(f"{API}/collect/tasks/{del_task}")
    report("S4-6 任务可删除", r.status_code == 200 and r2.status_code == 404,
           f"DEL {r.status_code} / GET {r2.status_code}")

    # ── S5 单条 IoT 上报（真值落库）──────────────────────────
    print("\n── S5 单条上报：压力 12.5 MPa ──")
    r = c.post(f"{API}/collect/iot/ingest", params={
        "device_code": f"PRS-{tag}", "point_name": "pressure",
        "value": "12.5", "quality": "good", "gateway_id": gw_id})
    got = (data(r) or {}).get("received")
    report("S5-1 单条上报接口可用", r.status_code == 200 and (got or 0) >= 1,
           f"HTTP {r.status_code} received={got} {msg(r)}")

    r = c.get(f"{API}/collect/records",
              params={"device_id": dev_id, "point_name": "pressure", "page_size": 50})
    recs = items(r)
    latest = recs[0] if recs else {}
    report("S5-2 上报值落库且可查", bool(recs), f"{len(recs)} 条")
    val = latest.get("value_numeric")
    report("S5-3 数值正确（12.5）", float(val) == 12.5 if val is not None else False,
           f"value_numeric={val}")
    report("S5-4 质量位随行落库", latest.get("quality") == "good",
           f"quality={latest.get('quality')}")

    # 非数值测点（字符串）也要能落
    r = c.post(f"{API}/collect/iot/ingest", params={
        "device_code": f"PRS-{tag}", "point_name": "batch_no",
        "value": "TD-20261103-001", "gateway_id": gw_id})
    r2 = c.get(f"{API}/collect/records",
               params={"device_id": dev_id, "point_name": "batch_no", "page_size": 10})
    recs = items(r2)
    report("S5-5 文本测点落 value_text",
           bool(recs) and (recs[0].get("value_text") or "").startswith("TD-"),
           f"value_text={recs[0].get('value_text') if recs else None}")

    # ── S6 批量上报 ────────────────────────────────────────────
    print("\n── S6 批量上报：5 条位移值 ──")
    now = datetime.now(timezone.utc)
    body = {"gateway_id": gw_id, "records": [
        {"device_id": dev_id, "gateway_id": gw_id,
         "data_time": (now - timedelta(minutes=i)).isoformat(),
         "point_name": f"disp_batch_{tag}", "value_numeric": 30 + i,
         "quality": "good", "source_type": "iot"} for i in range(5)]}
    r = c.post(f"{API}/collect/iot/ingest-batch", json=body)
    cnt = (data(r) or {}).get("received")
    report("S6-1 批量上报接口可用", r.status_code == 200 and (cnt or 0) == 5,
           f"HTTP {r.status_code} received={cnt} {msg(r)}")

    r = c.get(f"{API}/collect/records",
              params={"device_id": dev_id, "point_name": f"disp_batch_{tag}",
                      "page_size": 50})
    recs = items(r)
    report("S6-2 批量 5 条全部落库", len(recs) == 5, f"实际 {len(recs)} 条")

    # ── S7 记录直写 + 未来时间拒收 ────────────────────────────
    print("\n── S7 采集记录直写与时间护栏 ──")
    r = c.post(f"{API}/collect/records", json={
        "device_id": dev_id, "gateway_id": gw_id,
        "data_time": (now - timedelta(minutes=2)).isoformat(),
        "point_name": f"manual_{tag}", "value_numeric": 8.8,
        "quality": "good", "source_type": "manual"})
    ok_id = (data(r) or {}).get("id")
    report("S7-1 单条记录可直写", r.status_code == 200 and bool(ok_id),
           f"HTTP {r.status_code} id={ok_id} {msg(r) if not ok_id else ''}")
    report("S7-2 人工补录被标 is_backfill=False（2 分钟前）",
           (data(r) or {}).get("is_backfill") is False,
           f"is_backfill={(data(r) or {}).get('is_backfill')}")

    r = c.post(f"{API}/collect/records", json={
        "device_id": dev_id,
        "data_time": (now + timedelta(hours=3)).isoformat(),
        "point_name": f"future_{tag}", "value_numeric": 1.0})
    report("S7-3 未来时间被拒（时钟错乱护栏）", r.status_code == 400,
           f"HTTP {r.status_code} {msg(r)[:80]}")

    r = c.post(f"{API}/collect/records/batch", json={"records": [
        {"device_id": dev_id, "data_time": (now - timedelta(minutes=i)).isoformat(),
         "point_name": f"batch_direct_{tag}", "value_numeric": 100 + i} for i in range(3)]})
    report("S7-4 批量直写返回条数正确",
           r.status_code == 200 and (data(r) or {}).get("count") == 3,
           f"HTTP {r.status_code} count={(data(r) or {}).get('count')}")

    r = c.post(f"{API}/collect/records/batch", json={"records": [
        {"device_id": dev_id, "data_time": (now - timedelta(minutes=1)).isoformat(),
         "point_name": f"mix_{tag}", "value_numeric": 1.0},
        {"device_id": dev_id, "data_time": (now + timedelta(hours=5)).isoformat(),
         "point_name": f"mix_{tag}", "value_numeric": 2.0}]})
    report("S7-5 批量含未来数据时整批拒绝（不做部分写入）",
           r.status_code == 400, f"HTTP {r.status_code} {msg(r)[:80]}")

    r = c.get(f"{API}/collect/records",
              params={"device_id": dev_id, "page_size": 200})
    report("S7-6 记录列表可读", r.status_code == 200, f"HTTP {r.status_code}")

    # ── S8 链路监控 ────────────────────────────────────────────
    print("\n── S8 链路监控 ──")
    r = c.post(f"{API}/collect/monitors", json={
        "monitor_name": f"网关心跳{tag}", "monitor_type": "tcp",
        "target_host": "192.168.10.21", "target_port": 4840,
        "check_interval_seconds": 60, "timeout_seconds": 5})
    mon_id = (data(r) or {}).get("id")
    report("S8-1 链路监控可创建", r.status_code == 200 and bool(mon_id),
           f"HTTP {r.status_code} id={mon_id} {msg(r) if not mon_id else ''}")

    r = c.get(f"{API}/collect/monitors", params={"page_size": 100})
    rows = items(r)
    mon = next((m for m in rows if m.get("id") == mon_id), {})
    report("S8-2 监控出现在列表", bool(mon), f"共 {len(rows)} 条")
    report("S8-3 目标主机/端口落库",
           mon.get("target_host") == "192.168.10.21" and mon.get("target_port") == 4840,
           f"{mon.get('target_host')}:{mon.get('target_port')}")

    # ── S9 健康总览 ────────────────────────────────────────────
    print("\n── S9 采集健康总览 ──")
    r = c.get(f"{API}/collect/health")
    h = data(r) or {}
    report("S9-1 健康总览可读", r.status_code == 200 and isinstance(h, dict),
           f"HTTP {r.status_code} 键={list(h)[:6]}")
    report("S9-2 总览包含网关/设备/任务计数",
           any("gateway" in k.lower() for k in h) and any("device" in k.lower() for k in h),
           str({k: v for k, v in h.items() if isinstance(v, (int, float))})[:100])

    return finish()


def finish() -> int:
    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("断点：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
