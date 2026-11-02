"""热敏纸型的接口冒烟：同一接口两种纸、非法纸型、落库列、补打一致性。

`pytest app/tests/test_print.py` 只测渲染器（纯函数），浏览器 E2E 只测界面跳转，
**接口层的纸型语义两边都盖不到**，所以单独留这个脚本：

- `X-Print-Paper` 响应头是否与入参一致（前端靠它回显纸型）
- 非法纸型是否 400 而不是静默回落 A4（回落会让车间把归档件贴到工件上）
- `print_artifacts.paper_kind` 是否落库（补打时靠它挑出那张贴标）
- 补打是否逐字节一致（含二维码，说明没有重新渲染）

跑法（需先在本机起好 8000 端口的后端）：
    cd backend && .venv/Scripts/python.exe ../scripts/smoke_print_paper.py
"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def hget(h, name):
    """HTTP 头名大小写不敏感 —— urllib 交回来的是全小写键。"""
    return h.get(name) or h.get(name.lower())


def post(path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def get(path, token):
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read())
            # 统一响应体是 {code, message, data}，业务字段在 data 里
            return r.status, body.get("data", body)
    except urllib.error.HTTPError as e:
        return e.code, e.read()


st, _, body = post(
    "/auth/login",
    {"username": "mfg_admin", "password": "admin123", "tenant_code": "mfg_demo"},
)
assert st == 200, f"登录失败 {st} {body[:200]}"
tok = json.loads(body)["access_token"]
print("login OK")

st, lst = get("/work-orders?page=1&page_size=1", tok)
wo = (lst or {}).get("items", [])[0]
wid = wo["id"]
print("workorder", wid, wo.get("order_no"))

# 1) A4 归档件
st, h, pdf_a4 = post(f"/print/work_order/{wid}", None, tok)
print(f"[A4]     status={st} paper={hget(h, 'X-Print-Paper')} "
      f"pages={hget(h, 'X-Print-Page-Count')} tmpl={hget(h, 'X-Print-Template')} size={len(pdf_a4)}")
assert st == 200 and pdf_a4.startswith(b"%PDF-")
assert hget(h, "X-Print-Paper") == "a4"

# 2) 热敏贴标
st, h, pdf_label = post(f"/print/work_order/{wid}?paper=label80", None, tok)
print(f"[LABEL]  status={st} paper={hget(h, 'X-Print-Paper')} "
      f"pages={hget(h, 'X-Print-Page-Count')} tmpl={hget(h, 'X-Print-Template')} size={len(pdf_label)}")
assert st == 200 and hget(h, "X-Print-Paper") == "label80"
assert hget(h, "X-Print-Page-Count") == "1", "标签必须单页（卷筒纸多页会连成一条撕不开）"
assert hget(h, "X-Print-Template") == "WO-LABEL v1.0", "标签必须用标签模板，不能复用 A4 模板"
assert pdf_label != pdf_a4, "两种纸型不能出同一份 PDF"
label_artifact = int(hget(h, "X-Print-Artifact-Id"))
label_verify = hget(h, "X-Print-Verify-Code")

# 3) 非法纸型必须 400（不是回落到 A4 —— 悄悄改成 A4 会让车间把归档件贴到工件上）
st, _h, err = post(f"/print/work_order/{wid}?paper=A5", None, tok)
print(f"[BAD]    status={st} body={err.decode()[:110]}")
assert st == 400

# 4) 落库列
st, lst = get(f"/print/artifacts?doc_type=work_order&doc_id={wid}&page_size=5", tok)
rows = (lst or {}).get("items", [])
print("[LIST]  ", [(r["id"], r.get("paper_kind"), r["template_code"]) for r in rows[:4]])
assert any(r["id"] == label_artifact and r.get("paper_kind") == "label80" for r in rows), \
    "留痕列表要能区分纸型，否则补打时挑不出那张贴标"

# 5) 补打逐字节一致（含二维码 → 同一张纸可复现）
req = urllib.request.Request(BASE + f"/print/artifacts/{label_artifact}/pdf")
req.add_header("Authorization", "Bearer " + tok)
with urllib.request.urlopen(req) as r:
    back = r.read()
print(f"[REPRINT] size={len(back)} same_bytes={back == pdf_label}")
assert back == pdf_label, "补打必须逐字节相同（PDF 里已写死生成时间，不应重新渲染）"

# 6) 扫码回查
st, v1 = get(f"/print/verify/{label_verify}", tok)
print(f"[VERIFY]  found={v1.get('found')} valid={v1.get('valid')} doc_no={v1.get('doc_no')} paper={v1.get('paper')}")
assert v1.get("found") is True

print("\n全部通过")
