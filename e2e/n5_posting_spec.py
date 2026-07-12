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
USERNAME = os.getenv("USERNAME", "admin")
PASSWORD = os.getenv("PASSWORD", "admin123")
TENANT = os.getenv("TENANT", "default")

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
    """现存量 = 该物料在所有库位（含待检区）的 quantity 之和。"""
    resp = await client.get(f"{API}/wms/inventory", params={
        "material_id": material_id, "page_size": 1000,
    })
    data = resp.json().get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    return float(sum(i.get("quantity", 0) or 0 for i in items))


async def tx_summary(client: httpx.AsyncClient, material_id: int):
    """返回 (流水条数, 数量增量和)。"""
    resp = await client.get(f"{API}/wms/inventory-transactions", params={
        "material_id": material_id, "page_size": 1000,
    })
    data = resp.json().get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    count = len(items)
    total = float(sum(t.get("quantity", 0) or 0 for t in items))
    return count, total


def check(label: str, actual, expected):
    ok = actual == expected
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: actual={actual} expected={expected}")
    if not ok:
        raise SpecError(f"{label} 不满足：actual={actual} expected={expected}")


async def main():
    print(f"== N5 验收脚本（方案 B 确认即过账） base={BASE_URL} ==")
    async with httpx.AsyncClient(timeout=30) as client:
        token = await login(client)
        client.headers.update({"Authorization": f"Bearer {token}"})

        warehouse_id = await ensure_warehouse(client)
        material_id = await ensure_material(client)
        print(f"  使用 warehouse_id={warehouse_id} material_id={material_id}")

        # ① 收货登记 +100（pending → inspecting，待检区入账）
        ro = await client.post(f"{API}/wms/receipt-orders", json={
            "receipt_no": f"N5R-{os.getpid()}", "receipt_type": "purchase",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "expected_qty": EXP_RECEIVE, "unit": "PCS"}],
        })
        if ro.status_code != 200:
            raise SpecError(f"创建入库单失败 {ro.status_code}: {ro.text}")
        ro_id = ro.json()["data"]["id"]
        ro_items = (await client.get(f"{API}/wms/receipt-orders/{ro_id}")).json()["data"]["items"]
        item_id = ro_items[0]["id"]

        recv = await client.post(f"{API}/wms/receipt-order-items/{item_id}/receive",
                                 json={"received_qty": EXP_RECEIVE})
        if recv.status_code != 200:
            raise SpecError(f"收货登记失败 {recv.status_code}: {recv.text}")
        recv_status = (await client.get(f"{API}/wms/receipt-orders/{ro_id}")).json()["data"]["status"]
        check("收货后入库单状态=inspecting", recv_status, "inspecting")
        check("收货后现存量=100", await current_stock(client, material_id), float(EXP_RECEIVE))
        c1, s1 = await tx_summary(client, material_id)
        check("收货后流水=1", c1, 1)

        # ② 出库确认 -10
        io1 = await client.post(f"{API}/wms/issue-orders", json={
            "issue_no": f"N5I1-{os.getpid()}", "issue_type": "production",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "required_qty": EXP_ISSUE_1, "unit": "PCS"}],
        })
        io1_id = io1.json()["data"]["id"]
        io1_items = (await client.get(f"{API}/wms/issue-orders/{io1_id}")).json()["data"]["items"]
        iss1 = await client.post(f"{API}/wms/issue-order-items/{io1_items[0]['id']}/issue",
                                 json={"issued_qty": EXP_ISSUE_1})
        if iss1.status_code != 200:
            raise SpecError(f"出库确认1失败 {iss1.status_code}: {iss1.text}")
        check("发-10后现存量=90", await current_stock(client, material_id), float(EXP_RECEIVE - EXP_ISSUE_1))
        c2, s2 = await tx_summary(client, material_id)
        check("发-10后流水=2", c2, 2)

        # ③ 出库确认 -5
        io2 = await client.post(f"{API}/wms/issue-orders", json={
            "issue_no": f"N5I2-{os.getpid()}", "issue_type": "production",
            "warehouse_id": warehouse_id,
            "items": [{"line_no": 1, "material_id": material_id,
                       "required_qty": EXP_ISSUE_2, "unit": "PCS"}],
        })
        io2_id = io2.json()["data"]["id"]
        io2_items = (await client.get(f"{API}/wms/issue-orders/{io2_id}")).json()["data"]["items"]
        iss2 = await client.post(f"{API}/wms/issue-order-items/{io2_items[0]['id']}/issue",
                                 json={"issued_qty": EXP_ISSUE_2})
        if iss2.status_code != 200:
            raise SpecError(f"出库确认2失败 {iss2.status_code}: {iss2.text}")
        check("出-5后现存量=85", await current_stock(client, material_id), float(EXP_FINAL_STOCK))
        c3, s3 = await tx_summary(client, material_id)
        check("出-5后流水=3", c3, EXP_TX_COUNT)
        check("增量和=85", s3, float(EXP_TX_SUM))

    print("\n== N5 验收全部通过 ✅ ==")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        sys.exit(0)
    except SpecError as e:
        print(f"\n== N5 验收失败 ❌: {e} ==")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n== N5 验收异常 ❌: {e} ==")
        sys.exit(2)
