"""N5（数据对不拢）验收脚本 —— 方案 B 确认即过账（收+100 / 发-10 / 出-5）。

验证目标（对齐 deliverables/mfg1-n5-architecture-2026-07-12.md §5 T04/T05）：
  收 +100（收货登记 → 待检区入账，计入现存量）
  发 -10（出库确认 → 扣减库存 + 流水）
  出 -5 （出库确认 → 扣减库存 + 流水）
  => 现存量 = 85、流水 = 3 条、增量和 = 85

运行前置（由 QA + 主理人在用户重建镜像后执行，本地不跑线上探活）：
  - 后端已部署并包含本变更（posting_scope / receive_item 待检区入账 / issue 原子扣减）
  - 存在可用账号（DEFAULT_USERNAME / DEFAULT_PASSWORD 环境变量）

用法：
  python e2e/n5_posting_spec.py
  BASE_URL=http://x.x.x.x:8000 USERNAME=admin PASSWORD=secret python e2e/n5_posting_spec.py
"""
import asyncio
import os
import sys

import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
# ★别用裸 USERNAME/PASSWORD/TENANT：Windows 上 USERNAME 是系统内置变量
#   （当前登录名），会把默认账号顶掉，登录 401 却看不出原因。
USERNAME = os.getenv("E2E_USER", "mfg_admin")
PASSWORD = os.getenv("E2E_PASSWORD", "admin123")
TENANT = os.getenv("E2E_TENANT", "AH-THR")

API = f"{BASE_URL}/api/v1"

# 验收期望
EXP_RECEIVE = 100
EXP_ISSUE_1 = 10
EXP_ISSUE_2 = 5
EXP_FINAL_STOCK = 85          # 现存量（含待检区）：100 - 10 - 5
EXP_TX_COUNT = 3             # 流水条数
EXP_TX_SUM = 85              # 增量和：+100 -10 -5


class SpecError(Exception):
    """验收断言失败。"""


async def login(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        f"{API}/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    if resp.status_code != 200:
        raise SpecError(f"登录失败 {resp.status_code}: {resp.text}")
    token = resp.json().get("access_token")
    if not token:
        raise SpecError("登录响应缺少 access_token")
    return token


async def ensure_warehouse(client: httpx.AsyncClient) -> int:
    """优先复用现有仓库，否则创建一个。"""
    resp = await client.get(f"{API}/wms/warehouses", params={"page_size": 1})
    data = resp.json().get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    if items:
        return items[0]["id"]
    resp = await client.post(f"{API}/wms/warehouses", json={
        "code": f"N5WH-{os.getpid()}", "name": "N5验收仓", "type": "raw_material",
    })
    if resp.status_code != 200:
        raise SpecError(f"创建仓库失败 {resp.status_code}: {resp.text}")
    return resp.json()["data"]["id"]


async def ensure_material(client: httpx.AsyncClient) -> int:
    """优先复用现有物料，否则创建一个。"""
    resp = await client.get(f"{API}/wms/materials", params={"page_size": 1})
    data = resp.json().get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    if items:
        return items[0]["id"]
    resp = await client.post(f"{API}/wms/materials", json={
        "code": f"N5MAT-{os.getpid()}", "name": "N5验收物料", "unit": "PCS",
        "material_type": "raw", "pick_strategy": "fifo",
    })
    if resp.status_code != 200:
        raise SpecError(f"创建物料失败 {resp.status_code}: {resp.text}")
    return resp.json()["data"]["id"]


async def current_stock(client: httpx.AsyncClient, material_id: int) -> float:
    """现存量 = 该物料在所有库位（含待检区）的 quantity 之和。

    同样要翻页：inventory 是按 (库位 × 批次) 分行的，批次多起来一页装不下。
    """
    total = None
    collected = 0
    acc = 0.0
    page = 1
    while True:
        resp = await client.get(f"{API}/wms/inventory", params={
            "material_id": material_id, "page": page, "page_size": 100,
        })
        data = resp.json().get("data", {})
        items = data.get("items", [])
        if total is None:
            total = int(data.get("total") or 0)
        acc += sum(float(i.get("quantity", 0) or 0) for i in items)
        collected += len(items)
        if not items or collected >= total or page > 100:
            break
        page += 1
    return acc


async def tx_summary(client: httpx.AsyncClient, material_id: int):
    """返回 (流水总条数, 全部流水的数量增量和)。

    ★两个都必须按**全量**算，不能只数第一页：
      本脚本刻意复用已有物料（避免污染主数据），历史流水早就超过一页
      （staging 实测 total=174，而 page_size 上限 100）。只数当前页会恒等于
      100，收货多了一条也看不出变化 → 假红「收货后流水+1: actual=0」。
      这是探针假设错，不是过账算错（同一次运行的现存量 +100 是对的）。
    """
    total = None
    collected = 0
    acc = 0.0
    page = 1
    while True:
        resp = await client.get(f"{API}/wms/inventory-transactions", params={
            "material_id": material_id, "page": page, "page_size": 100,
        })
        data = resp.json().get("data", {})
        items = data.get("items", [])
        if total is None:
            total = int(data.get("total") or 0)
        acc += sum(float(t.get("quantity", 0) or 0) for t in items)
        collected += len(items)
        if not items or collected >= total or page > 100:
            break
        page += 1
    return (total or 0), acc


async def tx_by_docs(client: httpx.AsyncClient, doc_nos):
    """按**本次运行创建的单据号**取流水，返回 (条数, 数量净和)。

    ★为什么必须按单据号收敛，不能按物料取"全部流水增量"：
      ``ensure_material`` 复用列表第一条物料，它是全平台探针共用的热点物料；
      只要有任何别的写入落在同一物料上，``Σ全部流水 − 基线`` 就会漂移。
      实测单跑两次一红一绿（增量和 −6 / +6 双向漂移），而每一次的总账都自洽 ——
      这属于**探针假设错**，不是过账算错，但它会训练人忽略红。
      流水表的 ``source_doc_no`` 就是入库单号/出库单号（wms_service 写死为
      ``receipt_no`` / ``issue_no``），接口也支持按它过滤 → 可精确定位本次写入。
    """
    cnt = 0
    acc = 0.0
    for doc in doc_nos:
        page = 1
        while True:
            resp = await client.get(f"{API}/wms/inventory-transactions", params={
                "source_doc_no": doc, "page": page, "page_size": 100,
            })
            data = resp.json().get("data", {})
            items = data.get("items", [])
            cnt += len(items)
            acc += sum(float(t.get("quantity", 0) or 0) for t in items)
            if not items or page * 100 >= int(data.get("total") or 0) or page > 20:
                break
            page += 1
    return cnt, acc


_OK = 0


def check(label: str, actual, expected):
    global _OK
    ok = actual == expected
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: actual={actual} expected={expected}")
    if not ok:
        raise SpecError(f"{label} 不满足：actual={actual} expected={expected}")
    _OK += 1


def check_ge(label: str, actual, floor: int):
    """至少多少条 —— 用在"流水条数"这类会随批次拆分而变化的断言上。

    ★为什么不能钉死条数：本脚本复用已有物料，库存分散在多个批次/库位。
    FIFO 出库 10 时，若最早批次只剩 5，会拆成两条腿（5 + 5），于是写 **2 条**
    出库流水 —— 这是正确行为，不是缺陷。钉成"发-10 后流水正好 +2"只在
    "全新、单批次"的物料上成立，复用物料必然假红。
    **权威口径是数量增量和**（下面单独断言），条数只作弱校验。
    """
    global _OK
    ok = actual >= floor
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: actual={actual} expected>={floor}")
    if not ok:
        raise SpecError(f"{label} 不满足：actual={actual} expected>={floor}")
    _OK += 1


def check_near(label: str, actual: float, expected: float, tol: float = 0.01):
    global _OK
    ok = abs(actual - expected) <= tol
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: actual={actual} expected≈{expected} (tol={tol})")
    if not ok:
        raise SpecError(f"{label} 不满足：actual={actual} expected≈{expected}")
    _OK += 1


async def main():
    print(f"== N5 验收脚本（方案 B 确认即过账） base={BASE_URL} ==")
    async with httpx.AsyncClient(timeout=30) as client:
        token = await login(client)
        client.headers.update({"Authorization": f"Bearer {token}"})

        warehouse_id = await ensure_warehouse(client)
        material_id = await ensure_material(client)
        print(f"  使用 warehouse_id={warehouse_id} material_id={material_id}")

        # ⚠️ 库存断言仍是**相对基线**：原脚本写死绝对值（"收货后现存量=100"），
        # 只有在"该物料库存恰好为 0"的空库上跑第一次才成立。复用已有物料时
        # 基线不是 0，第二次跑就必红，看起来像"过账算错了"。
        # 但**流水断言不再用物料级基线**，改为按本次单据号收敛（见 tx_by_docs）：
        # 物料级增量和会被并发的其它写入污染，实测 −6 / +6 双向漂移。
        base_stock = await current_stock(client, material_id)
        print(f"  [BASELINE] 现存量={base_stock}（流水断言按本单号收敛，不取物料级基线）")
        ro_no = f"N5R-{os.getpid()}"
        my_docs = []   # 本次运行写出的单据号，流水断言只认这些

        # ① 收货登记 +100（pending → inspecting，待检区入账）
        ro = await client.post(f"{API}/wms/receipt-orders", json={
            "receipt_no": ro_no, "receipt_type": "purchase",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "expected_qty": EXP_RECEIVE, "unit": "PCS"}],
        })
        if ro.status_code != 200:
            raise SpecError(f"创建入库单失败 {ro.status_code}: {ro.text}")
        ro_id = ro.json()["data"]["id"]
        my_docs.append(ro_no)
        ro_items = (await client.get(f"{API}/wms/receipt-orders/{ro_id}")).json()["data"]["items"]
        item_id = ro_items[0]["id"]

        recv = await client.post(f"{API}/wms/receipt-order-items/{item_id}/receive",
                                 json={"received_qty": EXP_RECEIVE})
        if recv.status_code != 200:
            raise SpecError(f"收货登记失败 {recv.status_code}: {recv.text}")
        recv_status = (await client.get(f"{API}/wms/receipt-orders/{ro_id}")).json()["data"]["status"]
        check("收货后入库单状态=inspecting", recv_status, "inspecting")
        check_near("收货后现存量+100",
                   await current_stock(client, material_id) - base_stock, float(EXP_RECEIVE))
        c1, s1 = await tx_by_docs(client, my_docs)
        check("收货后本单流水=1条", c1, 1)
        check_near("收货后本单增量和=+100", s1, float(EXP_RECEIVE))

        # ② 出库确认 -10
        io1_no = f"N5I1-{os.getpid()}"
        io1 = await client.post(f"{API}/wms/issue-orders", json={
            "issue_no": io1_no, "issue_type": "production",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "required_qty": EXP_ISSUE_1, "unit": "PCS"}],
        })
        io1_id = io1.json()["data"]["id"]
        my_docs.append(io1_no)
        io1_items = (await client.get(f"{API}/wms/issue-orders/{io1_id}")).json()["data"]["items"]
        iss1 = await client.post(f"{API}/wms/issue-order-items/{io1_items[0]['id']}/issue",
                                 json={"issued_qty": EXP_ISSUE_1})
        if iss1.status_code != 200:
            raise SpecError(f"出库确认1失败 {iss1.status_code}: {iss1.text}")
        check_near("发-10后现存量=基线+90",
                   await current_stock(client, material_id) - base_stock,
                   float(EXP_RECEIVE - EXP_ISSUE_1))
        c2, s2 = await tx_by_docs(client, my_docs)
        check_ge("发-10后本单流水至少2条（批次拆分可能更多）", c2, 2)
        check_near("发-10后本单增量和=+90", s2, float(EXP_RECEIVE - EXP_ISSUE_1))

        # ③ 出库确认 -5
        io2_no = f"N5I2-{os.getpid()}"
        io2 = await client.post(f"{API}/wms/issue-orders", json={
            "issue_no": io2_no, "issue_type": "production",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "required_qty": EXP_ISSUE_2, "unit": "PCS"}],
        })
        io2_id = io2.json()["data"]["id"]
        my_docs.append(io2_no)
        io2_items = (await client.get(f"{API}/wms/issue-orders/{io2_id}")).json()["data"]["items"]
        iss2 = await client.post(f"{API}/wms/issue-order-items/{io2_items[0]['id']}/issue",
                                 json={"issued_qty": EXP_ISSUE_2})
        if iss2.status_code != 200:
            raise SpecError(f"出库确认2失败 {iss2.status_code}: {iss2.text}")
        check_near("出-5后现存量=基线+85",
                   await current_stock(client, material_id) - base_stock, float(EXP_FINAL_STOCK))
        c3, s3 = await tx_by_docs(client, my_docs)
        check_ge("出-5后本单流水至少3条（批次拆分可能更多）", c3, EXP_TX_COUNT)
        check_near("本单增量和=+85", s3, float(EXP_TX_SUM))

        # ============================================
        # T05 扩展 — cancel 状态感知红冲验收
        # ============================================

        # cancel-10：取消 pending 状态的收货单（零库存影响）
        ro_pending = await client.post(f"{API}/wms/receipt-orders", json={
            "receipt_no": f"N5RC-{os.getpid()}", "receipt_type": "purchase",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "expected_qty": 50, "unit": "PCS"}],
        })
        ro_pending_id = ro_pending.json()["data"]["id"]
        # ★这里必须用**物料级**读数，不能拿上面 doc 收敛的 c3 当基准 ——
        # c3 只统计 my_docs 里的三个单号，量纲不同，混比会恒假红。
        # 取消一张 **pending** 入库单不产生任何流水，所以物料级条数应当完全不变；
        # 因此取「取消前一刻」的物料级读数做基准（相邻两次读，污染窗口最小）。
        c_pre_cancel10, _ = await tx_summary(client, material_id)
        cancel10 = await client.post(
            f"{API}/wms/receipt-orders/{ro_pending_id}/cancel",
            json={"reason": "测试-取消未收货单据"},
        )
        if cancel10.status_code != 200:
            raise SpecError(f"cancel-10 失败 {cancel10.status_code}: {cancel10.text}")
        ro_pending_status = (await client.get(
            f"{API}/wms/receipt-orders/{ro_pending_id}",
        )).json()["data"]["status"]
        check("cancel-10 入库单 status=cancelled", ro_pending_status, "cancelled")
        check_near("cancel-10 库存不变", await current_stock(client, material_id),
                   base_stock + EXP_FINAL_STOCK)
        c10, _ = await tx_summary(client, material_id)
        check("cancel-10 流水数不变", c10, c_pre_cancel10)

        # cancel-11：取消已收货（inspecting）状态的收货单
        N_CANCEL11 = 30
        ro_insp = await client.post(f"{API}/wms/receipt-orders", json={
            "receipt_no": f"N5RI-{os.getpid()}", "receipt_type": "purchase",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "expected_qty": N_CANCEL11, "unit": "PCS"}],
        })
        ro_insp_id = ro_insp.json()["data"]["id"]
        ro_insp_items = (await client.get(
            f"{API}/wms/receipt-orders/{ro_insp_id}",
        )).json()["data"]["items"]
        recv_insp = await client.post(
            f"{API}/wms/receipt-order-items/{ro_insp_items[0]['id']}/receive",
            json={"received_qty": N_CANCEL11},
        )
        if recv_insp.status_code != 200:
            raise SpecError(f"cancel-11 收货失败 {recv_insp.status_code}: {recv_insp.text}")
        stock_before_c11 = await current_stock(client, material_id)
        tx_before_c11, _ = await tx_summary(client, material_id)
        cancel11 = await client.post(
            f"{API}/wms/receipt-orders/{ro_insp_id}/cancel",
            json={"reason": "来料不合格"},
        )
        if cancel11.status_code != 200:
            raise SpecError(f"cancel-11 失败 {cancel11.status_code}: {cancel11.text}")
        ro_insp_status = (await client.get(
            f"{API}/wms/receipt-orders/{ro_insp_id}",
        )).json()["data"]["status"]
        check("cancel-11 入库单 status=cancelled", ro_insp_status, "cancelled")
        check_near("cancel-11 库存-N（待检区回滚）",
                   await current_stock(client, material_id),
                   float(stock_before_c11 - N_CANCEL11))
        c11, _ = await tx_summary(client, material_id)
        check_ge("cancel-11 流水至少+1（多一条 cancel 流水）",
                 c11 - tx_before_c11, 1)

        # cancel-12：取消已出库（issued）状态的出库单
        M_CANCEL12 = 8
        io_issued = await client.post(f"{API}/wms/issue-orders", json={
            "issue_no": f"N5II-{os.getpid()}", "issue_type": "production",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "required_qty": M_CANCEL12, "unit": "PCS"}],
        })
        io_issued_id = io_issued.json()["data"]["id"]
        io_issued_items = (await client.get(
            f"{API}/wms/issue-orders/{io_issued_id}",
        )).json()["data"]["items"]
        iss12 = await client.post(
            f"{API}/wms/issue-order-items/{io_issued_items[0]['id']}/issue",
            json={"issued_qty": M_CANCEL12},
        )
        if iss12.status_code != 200:
            raise SpecError(f"cancel-12 出库失败 {iss12.status_code}: {iss12.text}")
        stock_before_c12 = await current_stock(client, material_id)
        tx_before_c12, _ = await tx_summary(client, material_id)
        cancel12 = await client.post(
            f"{API}/wms/issue-orders/{io_issued_id}/cancel",
            json={"reason": "发错料"},
        )
        if cancel12.status_code != 200:
            raise SpecError(f"cancel-12 失败 {cancel12.status_code}: {cancel12.text}")
        io_issued_status = (await client.get(
            f"{API}/wms/issue-orders/{io_issued_id}",
        )).json()["data"]["status"]
        check("cancel-12 出库单 status=cancelled", io_issued_status, "cancelled")
        check_near("cancel-12 库存+M（原库位回滚）",
                   await current_stock(client, material_id),
                   float(stock_before_c12 + M_CANCEL12))
        c12, _ = await tx_summary(client, material_id)
        # 出库红冲按**原始出库流水逐腿回滚**，原出库拆了几条腿就写几条 cancel 流水
        check_ge("cancel-12 流水至少+1（多一条 cancel 流水）",
                 c12 - tx_before_c12, 1)

    print("\n== N5 验收全部通过 ✅ ==")
    # run_all.py 靠这一行统计，缺了就会被判成"未输出可识别汇总"
    print(f"汇总：通 {_OK} / 断 0")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        sys.exit(0)
    except SpecError as e:
        print(f"\n== N5 验收失败 ❌: {e} ==")
        print(f"汇总：通 {_OK} / 断 1")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n== N5 验收异常 ❌: {e} ==")
        print(f"汇总：通 {_OK} / 断 1")
        sys.exit(2)
