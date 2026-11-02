"""T04 三页对应端点的本地冒烟（阶段② 前置）。

只判 HTTP 状态与关键字段是否存在，不做业务断言——业务由浏览器 E2E 验。
令牌从 _login.json 读取，不打印。

★ 断言基准的几个坑（踩过）：
  · 出库详情的明细字段叫 `items`；`lines` 只出现在 `/wms/issue-orders/scan`
    的返回里，且**只有 scan 带 can_execute / blocked_reason / suggest_***
    （前端 IssueOrderDetail 就是走 scan，不是走详情）。
  · 设备编码是 `MC-001` 这种，不是 `EQ-...`。
  · 点检清单在"任务无 plan_id 且计划无 checklist_template"时返回 **0 项且
    template_source='none'** —— 这是**设计内的真实状态**（现网 33 个计划
    模板全空、任务项 0 行），页面给「标准模板 / 手动添加」两条出路，
    所以这里不能断言 items>0。
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"

with open("_login.json", encoding="utf-8") as f:
    TOKEN = json.load(f)["access_token"]


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"raw": e.read()[:200].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return -1, {"err": str(e)[:160]}


def data_of(payload):
    return payload.get("data", payload) if isinstance(payload, dict) else {}


# (标签, method, path, body, 期望状态, 必含字段, 额外断言)
CASES = [
    ("点检清单·0 项是设计内状态", "GET", "/maintenance-tasks/79/checklist", None, 200,
     ["items", "template_source", "item_count"],
     lambda d: d["template_source"] == "none" and d["item_count"] == 0),
    ("点检清单·任务不存在", "GET", "/maintenance-tasks/999999/checklist", None, 404, None, None),
    ("扫设备码·MC-001", "GET", "/equipment/scan?code=MC-001", None, 200,
     ["equipment", "tasks"],
     lambda d: d["equipment"]["equipment_code"] == "MC-001"),
    ("扫设备码·不存在", "GET", "/equipment/scan?code=NOPE-XYZ", None, 404, None, None),
    ("出库扫单·lines+can_execute", "GET",
     "/wms/issue-orders/scan?code=II-QD-1101185240", None, 200,
     ["lines", "can_execute", "summary"],
     lambda d: len(d["lines"]) >= 1 and "remain_qty" in d["lines"][0]),
    ("出库扫单·不存在", "GET", "/wms/issue-orders/scan?code=NOPE-XYZ", None, 404, None, None),
    # 检验清单的降级标记是 `degraded` 布尔（不是 template_source）—— 更明确：
    # 前端 InspectionExecute 就是靠它决定是否停在"选标准"这一步。
    ("检验清单·有标准(725)", "GET", "/inspection-orders/725/checklist", None, 200,
     ["items", "degraded"], lambda d: d["degraded"] is False and len(d["items"]) >= 1),
    ("检验清单·无标准(723)走 degraded", "GET", "/inspection-orders/723/checklist", None, 200,
     ["items", "degraded"], lambda d: d["degraded"] is True and len(d["items"]) >= 1),
]

fails = []
for label, method, path, body, want, must, extra in CASES:
    st, payload = call(method, path, body)
    ok, note = True, []
    if want is not None and st != want:
        ok = False
        note.append(f"期望 {want}")
    if st >= 500 or st == -1:
        ok = False
    d = data_of(payload) if st < 400 else {}
    if must:
        for k in must:
            if k not in d:
                ok = False
                note.append(f"缺字段 {k}")
                break
    if ok and extra is not None:
        try:
            if not extra(d):
                ok = False
                note.append("额外断言不成立")
        except Exception as e:  # noqa: BLE001
            ok = False
            note.append(f"额外断言异常 {e}")
    if isinstance(d, dict):
        for k in ("items", "lines"):
            if isinstance(d.get(k), list):
                note.append(f"{k}={len(d[k])}")
        if "template_source" in d:
            note.append(f"src={d['template_source']}")
        if "can_execute" in d:
            note.append(f"can_execute={d['can_execute']}")
    print(f"{'OK  ' if ok else 'FAIL'} [{st}] {label}  {'；'.join(note)}")
    if not ok:
        fails.append((label, path, st, json.dumps(payload, ensure_ascii=False)[:240], "；".join(note)))

print()
if fails:
    print(f"=== {len(fails)} 项失败 ===")
    for label, path, st, detail, note in fails:
        print(f"- {label} {path} -> {st} {note}\n  {detail}")
    sys.exit(1)
print("=== 全部通过 ===")
