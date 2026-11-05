"""检验结果录入端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/inspection_entry_e2e.py

覆盖（BACKLOG C-79，用户拍板第 2 条：
"有需要结果录入界面，也要预留小程序端进行录入以及扫码方式的交互，
还有与检测设备对接录入预留接口"）：

    I-1  建单后 result 为空（未判定）—— 不再写 'pending' 占位
    I-2  批量录入 3 条：按上下限**自动判定**（10.02→PASS / 45→FAIL / 无数值+人工→FAIL）
    I-3  明细回读：spec_value 自动拼区间、measured_at 落库、source=web
    I-4  人工覆盖矛盾：数值超上限却判 PASS → 允许但进 conflicts（不静默吞）
    I-5  同单同项**幂等**：复测是更新不是再插一行
    I-6  已判定单**拒录**（判定是终态，判完改数等于篡改判定依据）
    I-7  扫码三种码：检验单号 / 流转卡工单号 / 垃圾码
    I-8  待录入清单：未判定的在、已判定的不在
    I-9  设备推送：按单聚合、坏单进 rejected 不拖垮整批、source=device+device_code 落库
    I-10 三通道 source 可区分（miniapp / device / web），非法通道拒绝
"""
import os
import sys
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def err_msg(r):
    try:
        d = r.json().get("detail")
        if isinstance(d, dict):
            return d.get("message", "")
        if isinstance(d, list):  # pydantic 422
            return "; ".join(str(x.get("msg")) for x in d)[:160]
        return str(d)
    except Exception:
        return ""


def data_of(r):
    return (r.json() or {}).get("data")


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {err_msg(r)}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    # ── 造参照数据：标准 + 3 个检验项 ─────────────────────────
    print("── 准备检验标准与检验项 ──")
    r = c.post(f"{API}/inspection-standards", json={
        "name": f"C79 录入验证标准 {tag}", "standard_type": "enterprise"})
    if r.status_code != 200:
        print(f"[FATAL] 建标准失败 {r.status_code} {err_msg(r)}")
        return 1
    r = c.get(f"{API}/inspection-standards", params={"keyword": f"C79 录入验证标准 {tag}"})
    std = (data_of(r) or {}).get("items") or []
    if not std:
        print("[FATAL] 标准未查到")
        return 1
    std_id = std[0]["id"]

    def mk_item(name, upper=None, lower=None, unit="mm"):
        return c.post(f"{API}/inspection-items", json={
            "standard_id": std_id, "item_name": name,
            "spec_upper_limit": upper, "spec_lower_limit": lower, "unit": unit})

    mk_item("长度", 10.05, 9.95)
    mk_item("硬度", 60, 50, "HRC")
    mk_item("外观", None, None, "")
    r = c.get(f"{API}/inspection-items", params={"standard_id": std_id, "page_size": 50})
    items = (data_of(r) or {}).get("items") or []
    by_name = {x["item_name"]: x["id"] for x in items}
    check("准备项齐全（长度/硬度/外观）", {"长度", "硬度", "外观"} <= set(by_name),
          str(sorted(by_name)))
    if not {"长度", "硬度", "外观"} <= set(by_name):
        return report()

    # ── I-1 建单 ────────────────────────────────────────────
    print("\n── C-79 检验结果录入 ──")
    r = c.post(f"{API}/inspection-orders", json={"order_type": "first"})
    ok = r.status_code == 200
    order_id = (data_of(r) or {}).get("id") if ok else None
    check("I-1 建单成功", ok, f"HTTP {r.status_code} {err_msg(r)[:80]}")
    if not ok:
        return report()
    r = c.get(f"{API}/inspection-orders/{order_id}")
    order = data_of(r) or {}
    check("I-1 建单后 result 为空（未判定），不是 'pending' 占位",
          order.get("result") in (None, ""), f"result={order.get('result')!r}")
    order_no = order.get("order_no")

    # ── I-2 批量录入 + 自动判定 ─────────────────────────────
    r = c.post(f"{API}/inspection-orders/{order_id}/results/batch", json={
        "source": "web",
        "results": [
            {"item_id": by_name["长度"], "measured_value": 10.02},
            {"item_id": by_name["硬度"], "measured_value": 45},
            {"item_id": by_name["外观"], "result": "FAIL", "remark": "划伤 3mm"},
        ]})
    ok = r.status_code == 200
    d = data_of(r) or {}
    check("I-2 批量录入 3 条成功", ok, f"HTTP {r.status_code} {err_msg(r)[:100]}")
    check("I-2 全部为新建", d.get("created") == 3 and d.get("updated") == 0,
          f"created={d.get('created')} updated={d.get('updated')}")
    check("I-2 自动判定生效：10.02→PASS、45→FAIL（只报数值即可）",
          {x["item_id"]: x["result"] for x in (d.get("results") or [])}
          == {by_name["长度"]: "PASS", by_name["硬度"]: "FAIL",
              by_name["外观"]: "FAIL"},
          str({x.get("item_id"): x.get("result") for x in (d.get("results") or [])}))
    check("I-2 不合格项被点名（现场要知道哪几项没过）",
          {"硬度", "外观"} <= set(d.get("failed_items") or []),
          str(d.get("failed_items")))

    # ── I-3 明细回读 ────────────────────────────────────────
    r = c.get(f"{API}/inspection-orders/{order_id}/results")
    rows = data_of(r) or []
    check("I-3 明细可回读（3 条）", len(rows) == 3, f"n={len(rows)}")
    len_row = next((x for x in rows if x.get("item_id") == by_name["长度"]), {})
    check("I-3 spec_value 自动拼成区间描述（不用手填规格）",
          len_row.get("spec_value") == "9.95~10.05", f"{len_row.get('spec_value')!r}")
    check("I-3 measured_at 落库（测量时刻，设备补传时与写库时刻分离）",
          bool(len_row.get("measured_at")), f"{len_row.get('measured_at')!r}")
    check("I-3 source=web 落库（三通道可区分）",
          all(x.get("source") == "web" for x in rows),
          str({x.get("source") for x in rows}))

    # ── I-4 人工覆盖矛盾 ────────────────────────────────────
    r = c.post(f"{API}/inspection-orders/{order_id}/results/batch", json={
        "source": "web",
        "results": [{"item_id": by_name["长度"], "measured_value": 10.5,
                     "result": "PASS", "remark": "让步接收（客户书面同意）"}]})
    d = data_of(r) or {}
    check("I-4 人工结论优先（让步接收能录）",
          d.get("updated") == 1, f"updated={d.get('updated')} HTTP {r.status_code}")
    check("I-4 数值与结论矛盾必须留痕（不静默吞）",
          bool(d.get("conflicts")), str(d.get("conflicts"))[:120])

    # ── I-5 同项复测幂等 ────────────────────────────────────
    r = c.post(f"{API}/inspection-orders/{order_id}/results/batch", json={
        "source": "web",
        "results": [{"item_id": by_name["长度"], "measured_value": 10.00}]})
    d = data_of(r) or {}
    check("I-5 复测是更新不是再插一行",
          d.get("updated") == 1 and d.get("created") == 0,
          f"updated={d.get('updated')} created={d.get('created')}")
    r = c.get(f"{API}/inspection-orders/{order_id}/results")
    rows = data_of(r) or []
    same = [x for x in rows if x.get("item_id") == by_name["长度"]]
    check("I-5 同单同项只有一行（不用翻时间戳才知道这项到底过没过）",
          len(same) == 1, f"n={len(same)}")
    check("I-5 复测后取最新值 10.0 且自动判 PASS",
          same and float(same[0]["measured_value"]) == 10.0
          and same[0]["result"] == "PASS",
          str(same[0]) if same else "无行")

    # ── I-6 已判定单拒录 ────────────────────────────────────
    r = c.put(f"{API}/inspection-orders/{order_id}/judge", json={"result": "ACC"})
    check("I-6 判定 ACC 成功", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.post(f"{API}/inspection-orders/{order_id}/results/batch", json={
        "source": "web", "results": [{"item_id": by_name["硬度"], "measured_value": 55}]})
    check("I-6 已判定单拒录 → 400 且说明原因",
          r.status_code == 400 and "已判定" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:100]}")

    # ── I-7 扫码 ────────────────────────────────────────────
    r = c.get(f"{API}/inspection-orders/scan", params={"code": order_no})
    d = data_of(r) or {}
    check("I-7 扫检验单号命中",
          r.status_code == 200 and (d.get("order") or {}).get("id") == order_id,
          f"HTTP {r.status_code} {err_msg(r)[:80]}")
    check("I-7 已判定的单扫出来告诉不可录入（不是让人白跑一趟）",
          d.get("judged") is True and "不可录入" in (d.get("action") or ""),
          str(d.get("action")))

    # 扫流转卡工单号：造一张挂在工单上的检验单
    r = c.get(f"{API}/work-orders", params={"page": 1, "page_size": 1})
    wos = (data_of(r) or {}).get("items") or []
    wo = wos[0] if wos else None
    if wo:
        r = c.post(f"{API}/inspection-orders", json={
            "order_type": "inspection", "work_order_id": wo["id"]})
        wo_order_id = (data_of(r) or {}).get("id") if r.status_code == 200 else None
        r = c.get(f"{API}/inspection-orders/scan", params={"code": wo["wo_no"]})
        d = data_of(r) or {}
        check("I-7 扫流转卡工单号 → 反查到该工单的待检单",
              r.status_code == 200 and (d.get("order") or {}).get("work_order_id") == wo["id"],
              f"HTTP {r.status_code} wo={wo.get('wo_no')} "
              f"got={(d.get('order') or {}).get('id')} want={wo_order_id}")
    else:
        wo_order_id = None
        check("I-7 扫流转卡工单号 → 反查到该工单的待检单", False, "租户内无工单，跳过")

    r = c.get(f"{API}/inspection-orders/scan", params={"code": f"MAT-{tag}-NOT-EXIST"})
    check("I-7 扫到无关的码 → 404 且给人话（不是空响应）",
          r.status_code == 404 and "没找到" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:100]}")

    # ── I-8 待录入清单 ──────────────────────────────────────
    r = c.get(f"{API}/inspection-orders/pending-entry", params={"limit": 200})
    d = data_of(r) or {}
    ids = {x["id"] for x in (d.get("items") or [])}
    check("I-8 待录入清单只含未判定单（已判定的不在）",
          (order_id not in ids) and (bool(ids)),
          f"n={len(ids)} 已判定单出现={order_id in ids}")
    check("I-8 带 recorded_count（现场关心还差几项没测）",
          all("recorded_count" in x for x in (d.get("items") or [])),
          str((d.get("items") or [{}])[0])[:120])

    # ── I-9 设备直连推送 ────────────────────────────────────
    r = c.post(f"{API}/inspection-results/device-push", json={
        "results": [{"order_no": order_no, "item_id": by_name["硬度"], "measured_value": 55}]})
    check("I-9 设备推送缺 device_code → 422（数据必须能溯源到量具）",
          r.status_code == 422, f"HTTP {r.status_code}")

    target = wo_order_id or order_id
    r = c.get(f"{API}/inspection-orders/{target}")
    target_no = (data_of(r) or {}).get("order_no")
    r = c.post(f"{API}/inspection-results/device-push", json={
        "device_code": f"MITUTOYO-{tag}",
        "results": [
            {"order_no": target_no, "item_id": by_name["长度"], "measured_value": 10.01},
            {"order_no": target_no, "item_id": by_name["硬度"], "measured_value": 58},
            {"order_no": f"QC-NOT-EXIST-{tag}", "item_id": by_name["长度"],
             "measured_value": 1.0},
            {"order_no": order_no, "item_id": by_name["硬度"], "measured_value": 55},
        ]})
    ok = r.status_code == 200
    d = data_of(r) or {}
    check("I-9 设备推送成功", ok, f"HTTP {r.status_code} {err_msg(r)[:100]}")
    check("I-9 按单聚合成批次（同单多项一次写）",
          len(d.get("batches") or []) == 1, f"batches={len(d.get('batches') or [])}")
    check("I-9 正常行被接收（accepted=2）", d.get("accepted") == 2,
          f"accepted={d.get('accepted')}")
    reasons = " | ".join(str(x.get("reason")) for x in (d.get("rejected") or []))
    check("I-9 不存在的单进 rejected", "检验单不存在" in reasons, reasons[:120])
    check("I-9 已判定的单进 rejected 但不拖垮整批（已收的先收）",
          "已判定" in reasons and (d.get("accepted") or 0) > 0, reasons[:160])

    r = c.get(f"{API}/inspection-orders/{target}/results")
    rows = data_of(r) or []
    dev = [x for x in rows if x.get("source") == "device"]
    check("I-9 source=device + device_code 落库（事后分得清设备直采与人手抄）",
          dev and all(x.get("device_code") == f"MITUTOYO-{tag}" for x in dev),
          f"n={len(dev)} codes={ {x.get('device_code') for x in dev} }")

    # ── I-10 三通道 source ─────────────────────────────────
    r = c.post(f"{API}/inspection-orders", json={"order_type": "spot_check"})
    o2 = (data_of(r) or {}).get("id")
    r = c.post(f"{API}/inspection-orders/{o2}/results/batch", json={
        "source": "miniapp",
        "results": [{"item_id": by_name["长度"], "measured_value": 9.99}]})
    d = data_of(r) or {}
    check("I-10 小程序通道可录（source=miniapp）",
          r.status_code == 200 and d.get("source") == "miniapp",
          f"HTTP {r.status_code} source={d.get('source')}")
    r = c.get(f"{API}/inspection-orders/{o2}/results")
    rows = data_of(r) or []
    check("I-10 miniapp 落库", rows and rows[0].get("source") == "miniapp",
          str({x.get("source") for x in rows}))

    r = c.post(f"{API}/inspection-orders/{o2}/results/batch", json={
        "source": "telepathy", "results": [{"item_id": by_name["长度"], "measured_value": 9.9}]})
    check("I-10 未知通道 → 400 点名（不是静默按 web 存）",
          r.status_code == 400 and "通道" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:100]}")

    return report()


def report():
    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
