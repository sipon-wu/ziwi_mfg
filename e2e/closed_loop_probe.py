import requests, json

BASE = "https://mfg1.ziwi.cn/api/v1"
TENANT = "mfg_demo"
PW = "test123456"

def login():
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": "test_admin", "password": PW, "tenant_id": TENANT},
                      timeout=20)
    print("LOGIN", r.status_code, r.text[:400])
    r.raise_for_status()
    return r.json()["access_token"]

tok = login()
H = {"Authorization": f"Bearer {tok}"}

def call(method, path, json=None, params=None):
    r = requests.request(method, f"{BASE}{path}", json=json, params=params, headers=H, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body

def show(label, s, body, n=900):
    print(f"\n=== {label}  [{s}] ===")
    print(json.dumps(body, ensure_ascii=False)[:n])

# 1) warehouses
s, b = call("GET", "/wms/warehouses")
show("WAREHOUSES", s, b)
try:
    wh = (b["data"] if isinstance(b["data"], list) else b["data"].get("list", []))[0]
    WH_ID = wh["id"]
    print(">> WH_ID =", WH_ID, "name=", wh.get("name"))
except Exception as e:
    WH_ID = None
    print(">> WH parse fail:", e)

# 2) materials list
s, b = call("GET", "/wms/materials", params={"page_size": 3})
show("MATERIALS", s, b)
try:
    mlist = b["data"] if isinstance(b["data"], list) else b["data"].get("list", [])
    MAT0 = mlist[0]["id"]
    print(">> MAT0 id=", MAT0, "sample=", json.dumps(mlist[0], ensure_ascii=False)[:300])
except Exception as e:
    MAT0 = None
    print(">> MAT parse fail:", e)

# 3) inventory by-material for MAT0
if MAT0:
    s, b = call("GET", f"/wms/inventory/by-material", params={"material_id": MAT0})
    show("INVENTORY_BY_MAT", s, b, 700)

# 4) boms
s, b = call("GET", "/boms", params={"page_size": 2})
show("BOMS", s, b, 700)

# 5) products - try candidate paths
for p in ["/products", "/basic-data/products", "/product"]:
    s, b = call("GET", p, params={"page_size": 2})
    print(f"\n=== PRODUCTS path={p} [{s}] ===")
    print(json.dumps(b, ensure_ascii=False)[:400])

# 6) material create required fields (minimal)
s, b = call("POST", "/wms/materials", json={"code": "E2E_PROBE_MAT", "name": "探针物料", "unit": "PCS", "pick_strategy": "fifo"})
show("MAT_CREATE_MIN", s, b, 500)

# 7) kanban / alert endpoints
s, b = call("GET", "/andon/calls", params={"status": ""})
show("ANDON_CALLS", s, b, 500)
s, b = call("GET", "/wms/inventory-alerts")
show("INV_ALERTS", s, b, 400)
if WH_ID:
    s, b = call("GET", "/wms/reports/stock-summary", params={"warehouse_id": WH_ID})
    show("STOCK_SUMMARY", s, b, 400)

print("\nPROBE_DONE")
