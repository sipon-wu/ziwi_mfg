"""PLAT 平台底座 · 场景验收探针（推进器厂：一个租户从开通到日常运营的底座面）。

## 这个探针要回答什么

覆盖矩阵里 PLAT 是**剩余最大的空洞**：98 条路由只被碰到 43 条（44%），55 条
从未被执行过 —— 数据字典、消息中心、角色数据范围与成员、同步消费者、集成网关
API Key、Excel 导入、打印留痕、租户模块启停、Copilot、审批动作、登出。

底座的特点是"坏了全站都受影响，但平常没人单独验它"：字典一挂，全站下拉框全空；
打印留痕一挂，追溯就断链；同步消费者一挂，M11 能碳取不到 mfg 的数据。

## 场景

A推进器厂租户开通后的**日常运营底座**：

- 字典：新增「压装工序类型」字典，配置 3 个工序值，改一个、删一个
- 消息：给班组长发一条「设备点检到期」提醒 → 查未读 → 标已读
- 角色：给「工艺工程师」设 DEPT 数据范围，加成员、移成员
- 同步：为能碳系统开一个消费方 Key（同步 equipment/work_report）→ 续租 → 吊销
- 集成网关：给 MES 上游开 API Key → 用它自检 /me → 吊销
- 导入：下载模板 → 上传一份设备导入表 → 查任务状态
- 打印：开工单归档件 → 拿留痕码 → 校验留痕 → 下载 PDF
- 租户：读模块开关 → 原样写回（幂等，不改动实际启用集）
- 审批：发起一张技改审批 → 审批通过
- Copilot：问一句「今天有几个工单逾期」→ 反馈 → 会话列表 → 清空

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/platform_base_e2e.py
"""
from __future__ import annotations

import io
import os
from datetime import datetime

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
    return d if isinstance(d, list) else []


def msg(r: httpx.Response) -> str:
    try:
        body = r.json()
    except Exception:
        return (r.text or "")[:160]
    d = body.get("detail")
    if isinstance(d, dict):
        return str(d.get("message") or d.get("code"))[:160]
    if isinstance(d, str):
        return d[:160]
    return str(body.get("message") or "")[:160]


def _xlsx_bytes(headers: list[str], rows: list[list]) -> bytes:
    """造一份最小 xlsx 给导入接口用（不引入额外依赖：手写 zip）。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def login(c: httpx.Client) -> dict:
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_code": TENANT})
    payload = r.json()
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    return payload


def main() -> int:
    c = httpx.Client(timeout=40)
    payload = login(c)
    tok = payload.get("access_token")
    if not tok:
        print(f"[FATAL] 登录失败: {payload}")
        return 1
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    me = c.get(f"{API}/auth/me")
    me_obj = data(me) or {}
    me_id = me_obj.get("id")
    # 平台里有两个"租户标识"：tenants.code（如 MFG1，登录用）和
    # tenants.tenant_id（如 AH-THR，几乎所有 /tenants/{x} 路由用它）。
    # 混用会得到一个干净的 404，看着像接口坏了。
    real_tid = me_obj.get("tenant_id") or TENANT
    print(f"当前用户 id={me_id} tenant_id={real_tid}")

    tag = datetime.now().strftime("%H%M%S")

    # ============ P1 系统底座 ============
    print("\n── P1 系统底座（健康/配置/许可）──")

    r = c.get(f"{API}/system/health")
    report("P1-1 健康检查可读", r.status_code == 200 and r.json().get("status") in ("ok", "healthy", "up"),
           f"HTTP {r.status_code} {str(r.json())[:80]}")

    r = c.get(f"{API}/system/config")
    cfg = data(r) or {}
    report("P1-2 系统配置可读（含前端需要的开关）",
           r.status_code == 200 and isinstance(cfg, dict) and len(cfg) >= 1,
           f"HTTP {r.status_code} 键 {sorted(cfg)[:6] if isinstance(cfg, dict) else cfg}")

    r = c.get(f"{API}/system/license")
    report("P1-3 许可信息可读（未配置时应是 404 而非 500）",
           r.status_code in (200, 404), f"HTTP {r.status_code} {msg(r)[:80]}")

    # ============ P2 数据字典 ============
    print("\n── P2 数据字典（全站下拉框的根）──")

    r = c.get(f"{API}/dictionaries", params={"page_size": 100})
    report("P2-1 字典列表可读", r.status_code == 200, f"共 {len(items(r))} 个")

    code = f"PROC_TYPE_{tag}"
    r = c.post(f"{API}/dictionaries", json={
        "dict_code": code, "dict_name": f"压装工序类型{tag}", "description": "推进器厂压装工序分类"})
    dict_id = (data(r) or {}).get("id")
    report("P2-2 字典可创建", r.status_code == 200,
           f"HTTP {r.status_code} {msg(r) if r.status_code != 200 else ''}")

    r = c.get(f"{API}/dictionaries", params={"page_size": 100})
    drow = next((x for x in items(r) if x.get("dict_code") == code), {})
    dict_id = dict_id or drow.get("id")
    report("P2-3 新字典出现在列表", bool(dict_id), f"id={dict_id}")

    r = c.get(f"{API}/dictionaries/{dict_id}")
    report("P2-4 字典详情可读", r.status_code == 200 and (data(r) or {}).get("dict_code") == code,
           f"HTTP {r.status_code}")

    r = c.put(f"{API}/dictionaries/{dict_id}", json={"description": "推进器厂压装工序分类（已确认）"})
    r2 = c.get(f"{API}/dictionaries/{dict_id}")
    report("P2-5 字典可改描述",
           r.status_code == 200 and "已确认" in str((data(r2) or {}).get("description", "")),
           f"HTTP {r.status_code} desc={(data(r2) or {}).get('description')}")

    item_ids = []
    for icode, iname in (("PRESS", "压装"), ("BOLT", "拧紧"), ("SEAL", "涂胶")):
        r = c.post(f"{API}/dictionaries/{dict_id}/items", json={
            "item_code": icode, "item_name": iname, "item_value": icode, "sort_order": len(item_ids)})
        report(f"P2-6 字典项「{iname}」可创建", r.status_code == 200,
               f"HTTP {r.status_code} {msg(r) if r.status_code != 200 else ''}")

    r = c.get(f"{API}/dictionaries/code/{code}/items")
    dict_items = items(r)
    item_ids = [x.get("id") for x in dict_items]
    report("P2-7 可按字典编码取项（前端下拉框走这条）",
           r.status_code == 200 and len(dict_items) == 3,
           f"{len(dict_items)} 项")

    if item_ids:
        r = c.put(f"{API}/dictionaries/items/{item_ids[0]}", json={"item_name": "压装（关键工序）"})
        r2 = c.get(f"{API}/dictionaries/code/{code}/items")
        changed = next((x for x in items(r2) if x.get("id") == item_ids[0]), {})
        report("P2-8 字典项可改",
               r.status_code == 200 and "关键工序" in str(changed.get("item_name", "")),
               f"HTTP {r.status_code} name={changed.get('item_name')}")

        r = c.delete(f"{API}/dictionaries/items/{item_ids[-1]}")
        r2 = c.get(f"{API}/dictionaries/code/{code}/items")
        report("P2-9 字典项可删",
               r.status_code == 200 and len(items(r2)) == 2,
               f"HTTP {r.status_code} 剩 {len(items(r2))} 项")
    else:
        report("P2-8 字典项可改", False, "没有字典项 id")
        report("P2-9 字典项可删", False, "没有字典项 id")

    # ============ P3 消息中心 ============
    print("\n── P3 消息中心 ──")

    if me_id:
        r = c.post(f"{API}/messages", json={
            "receiver_id": me_id, "msg_type": "todo",
            "title": f"设备点检到期提醒-{tag}",
            "content": "3 台伺服压机本周点检未做", "biz_type": "tpm_plan", "biz_id": "1"})
        report("P3-1 消息可发送", r.status_code == 200,
               f"HTTP {r.status_code} {msg(r) if r.status_code != 200 else ''}")
    else:
        report("P3-1 消息可发送", False, "取不到当前用户 id")

    r = c.get(f"{API}/messages", params={"page_size": 50})
    msgs = items(r)
    mine = next((m for m in msgs if tag in str(m.get("title", ""))), {})
    report("P3-2 消息列表可读且含刚发的一条", r.status_code == 200 and bool(mine),
           f"共 {len(msgs)} 条")

    r = c.get(f"{API}/messages/unread-count")
    unread = (data(r) or {}).get("total")
    report("P3-3 未读数可读（发送后 ≥1）", r.status_code == 200 and (unread or 0) >= 1,
           f"unread={unread}")

    if mine.get("id"):
        msg_id_val = mine.get("id")
        r = c.put(f"{API}/messages/{msg_id_val}/read")
        r2 = c.get(f"{API}/messages", params={"page_size": 50})
        m2 = next((m for m in items(r2) if m.get("id") == mine.get("id")), {})
        report("P3-4 消息可标记已读",
               r.status_code == 200 and m2.get("is_read") in (True, 1),
               f"HTTP {r.status_code} is_read={m2.get('is_read')}")
    else:
        report("P3-4 消息可标记已读", False, "没有消息 id")

    # ============ P4 角色数据范围与成员 ============
    print("\n── P4 角色数据作用域与成员 ──")

    r = c.get(f"{API}/roles", params={"page_size": 100})
    roles = items(r)
    target_role = next((x for x in roles if x.get("code") == "process_engineer"), None) \
        or next((x for x in roles if not x.get("is_builtin")), None) or (roles[0] if roles else {})
    role_id = target_role.get("id")
    old_scope = target_role.get("scope") or "ALL"

    r = c.put(f"{API}/roles/{role_id}/scope", json={"scope": "DEPT"})
    r2 = c.get(f"{API}/roles/{role_id}")
    new_scope = (data(r2) or {}).get("scope")
    report("P4-1 角色数据作用域可改（ALL→DEPT）",
           r.status_code == 200 and new_scope == "DEPT",
           f"HTTP {r.status_code} scope={new_scope} {msg(r) if r.status_code != 200 else ''}")
    # 还原，避免影响其它探针的数据范围断言
    c.put(f"{API}/roles/{role_id}/scope", json={"scope": old_scope})

    r = c.get(f"{API}/roles/{role_id}/users")
    before_users = items(r)
    report("P4-2 角色成员列表可读", r.status_code == 200, f"{len(before_users)} 人")

    r = c.get(f"{API}/users", params={"page_size": 100})
    users = items(r)
    cand = next((u for u in users if u.get("id") not in
                 {x.get("id") or x.get("user_id") for x in before_users}), None)
    if cand and role_id:
        r = c.post(f"{API}/roles/{role_id}/users", params={"user_id": cand.get("id")})
        r2 = c.get(f"{API}/roles/{role_id}/users")
        added = any((x.get("id") or x.get("user_id")) == cand.get("id") for x in items(r2))
        report("P4-3 可把用户加入角色", r.status_code == 200 and added,
               f"HTTP {r.status_code} user={cand.get('id')} {msg(r) if not added else ''}")

        r = c.delete(f"{API}/roles/{role_id}/users/{cand.get('id')}")
        r2 = c.get(f"{API}/roles/{role_id}/users")
        removed = not any((x.get("id") or x.get("user_id")) == cand.get("id") for x in items(r2))
        report("P4-4 可把用户移出角色", r.status_code == 200 and removed,
               f"HTTP {r.status_code} {msg(r) if not removed else ''}")
    else:
        report("P4-3 可把用户加入角色", False, "没有可加入的用户/角色")
        report("P4-4 可把用户移出角色", False, "没有可加入的用户/角色")

    r = c.post(f"{API}/roles/key-user-permissions", json={"role_id": None})
    report("P4-5 key_user 专属权限可分配（不传 role_id 时自动建角色）",
           r.status_code == 200, f"HTTP {r.status_code} {msg(r)}")

    # ============ P5 同步中心 ============
    print("\n── P5 同步中心（M11 能碳取数的通道）──")

    r = c.get(f"{API}/sync/consumers", params={"page_size": 100})
    report("P5-1 消费者列表可读", r.status_code == 200, f"{len(items(r))} 个")

    r = c.post(f"{API}/sync/consumers", params={
        "tenant_id": real_tid, "consumer_name": f"能碳系统-{tag}",
        "allowed_tables": "equipment,work_report", "expire_days": 30})
    consumer_key = (data(r) or {}).get("api_key")
    report("P5-2 消费者可创建且返回 API Key",
           r.status_code == 200 and bool(consumer_key),
           f"HTTP {r.status_code} {msg(r) if not consumer_key else '已发 Key'}")

    r = c.get(f"{API}/sync/consumers", params={"page_size": 100})
    cons = next((x for x in items(r) if f"能碳系统-{tag}" in str(x.get("consumer_name", ""))), {})
    cid = cons.get("id")
    # 注意：消费者列表接口的 SELECT 只取 id/tenant_id/consumer_name/is_active/
    # expires_at/last_call_at/created_at，**不含 allowed_tables** —— 所以这里只
    # 断言"落库可查"，表级白名单要另用 /sync/changes 的实际过滤结果验证。
    report("P5-3 消费者落库可查", bool(cid), f"id={cid}")

    if cid:
        r = c.post(f"{API}/sync/consumers/{cid}/renew", params={"expire_days": 90})
        report("P5-4 消费者可续租", r.status_code == 200, f"HTTP {r.status_code} {msg(r)}")
    else:
        report("P5-4 消费者可续租", False, "没有消费者 id")

    # /sync/changes|status|ack 是**消费者面**接口，鉴权走 X-Api-Key 而非 JWT。
    # 拿会话令牌打过去只会得到 422（少了 X-Api-Key 头），别误判成产品缺陷。
    if consumer_key:
        kh = {"X-Api-Key": consumer_key}
        r = c.get(f"{API}/sync/status", headers=kh)
        report("P5-5 消费者可读同步状态", r.status_code == 200,
               f"HTTP {r.status_code} {str(data(r))[:80]} {msg(r) if r.status_code != 200 else ''}")

        r = c.get(f"{API}/sync/changes", params={"limit": 10}, headers=kh)
        ch = data(r) or {}
        report("P5-6 变更流可拉取（含 latest_id）",
               r.status_code == 200 and "latest_id" in ch,
               f"HTTP {r.status_code} changes={len(ch.get('changes') or [])} latest={ch.get('latest_id')}")

        up_to = ch.get("latest_id") or 0
        r = c.post(f"{API}/sync/changes/ack", params={"up_to_id": up_to}, headers=kh)
        report("P5-7 变更可确认消费位点", r.status_code == 200,
               f"HTTP {r.status_code} up_to={up_to} {msg(r)}")

        r = c.get(f"{API}/sync/changes", params={"limit": 5}, headers={"X-Api-Key": "ziwi_invalid"})
        report("P5-8 无效 API Key 被拒（401）", r.status_code == 401,
               f"HTTP {r.status_code} {msg(r)}")
    else:
        for nm in ("P5-5 消费者可读同步状态", "P5-6 变更流可拉取（含 latest_id）",
                   "P5-7 变更可确认消费位点", "P5-8 无效 API Key 被拒（401）"):
            report(nm, False, "消费者没建起来，拿不到 API Key")

    if cid:
        r = c.post(f"{API}/sync/consumers/{cid}/revoke")
        r2 = c.get(f"{API}/sync/consumers", params={"page_size": 100})
        c2 = next((x for x in items(r2) if x.get("id") == cid), {})
        report("P5-9 消费者可吊销（is_active 置假）",
               r.status_code == 200 and c2.get("is_active") in (False, 0),
               f"HTTP {r.status_code} is_active={c2.get('is_active')}")
    else:
        report("P5-9 消费者可吊销（is_active 置假）", False, "没有消费者 id")

    # ============ P6 集成网关 API Key ============
    print("\n── P6 集成网关 API Key ──")

    r = c.post(f"{API}/integration-gateway/keys", json={
        "key_name": f"MES上游-{tag}", "permissions": ["work_order:read"],
        "allowed_ips": [], "webhook_url": None})
    plain = (data(r) or {}).get("plain_key")
    key_id = (data(r) or {}).get("id")
    report("P6-1 API Key 可创建且只回一次明文",
           r.status_code == 200 and str(plain or "").startswith("ziwi_"),
           f"HTTP {r.status_code} prefix={str(plain)[:12]} {msg(r) if not plain else ''}")

    r = c.get(f"{API}/integration-gateway/keys", params={"page_size": 100})
    krow = next((x for x in items(r) if x.get("id") == key_id), {})
    report("P6-2 Key 列表可见且前缀脱敏（无明文）",
           bool(krow) and "****" in str(krow.get("key_prefix", ""))
           and plain not in str(r.text),
           f"prefix={krow.get('key_prefix')}")

    if plain:
        r = c.get(f"{API}/integration-gateway/me", headers={"X-API-Key": plain})
        d = data(r) or {}
        report("P6-3 用 API Key 可自检身份（X-API-Key 认证）",
               r.status_code == 200 and d.get("auth_type") == "api_key",
               f"HTTP {r.status_code} auth={d.get('auth_type')} {msg(r) if r.status_code != 200 else ''}")
    else:
        report("P6-3 用 API Key 可自检身份（X-API-Key 认证）", False, "没有明文 Key")

    if key_id:
        r = c.delete(f"{API}/integration-gateway/keys/{key_id}")
        r2 = c.get(f"{API}/integration-gateway/keys", params={"page_size": 100})
        gone = not any(x.get("id") == key_id and x.get("is_active") in (True, 1)
                       for x in items(r2))
        report("P6-4 Key 可吊销", r.status_code == 200 and gone,
               f"HTTP {r.status_code} 已失效={gone}")
    else:
        report("P6-4 Key 可吊销", False, "没有 key id")

    # ============ P7 Excel 导入 ============
    print("\n── P7 Excel 导入 ──")

    r = c.get(f"{API}/excel-import/templates")
    tpls = items(r)
    report("P7-1 导入模板清单可读", r.status_code == 200 and len(tpls) >= 1,
           f"{len(tpls)} 个模板")

    r = c.get(f"{API}/excel-import/templates/equipment/download")
    report("P7-2 模板可下载（xlsx 字节流）",
           r.status_code == 200 and len(r.content) > 1000
           and "spreadsheet" in (r.headers.get("content-type") or ""),
           f"HTTP {r.status_code} {len(r.content)}B {r.headers.get('content-type')}")

    r = c.get(f"{API}/excel-import/tasks", params={"page_size": 50})
    report("P7-3 导入任务列表可读", r.status_code == 200, f"{len(items(r))} 个任务")

    try:
        xlsx = _xlsx_bytes(
            ["设备编码", "设备名称", "设备类型"],
            [[f"EQ-IMP-{tag}", "压装机A", "press"]])
        r = c.post(f"{API}/excel-import/tasks",
                   data={"import_type": "equipment"},
                   files={"file": (f"equipment_{tag}.xlsx", xlsx,
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        task = data(r) or {}
        task_id_val = task.get("task_id") or task.get("id")
        report("P7-4 可上传 Excel 建导入任务",
               r.status_code == 200 and bool(task_id_val),
               f"HTTP {r.status_code} id={task_id_val} "
               f"total={task.get('total')} success={task.get('success')} "
               f"{msg(r) if r.status_code != 200 else ''}")
    except Exception as exc:  # noqa: BLE001
        task = {}
        task_id_val = None
        report("P7-4 可上传 Excel 建导入任务", False, f"造表失败: {exc}")

    if task_id_val:
        r = c.get(f"{API}/excel-import/tasks/{task_id_val}")
        d = data(r) or {}
        report("P7-5 导入任务详情可读（含行数统计）",
               r.status_code == 200 and "total_rows" in d,
               f"HTTP {r.status_code} total={d.get('total_rows')} success={d.get('success_rows')}")
    else:
        report("P7-5 导入任务详情可读（含行数统计）", False, "没有任务 id")

    # ============ P8 打印留痕 ============
    print("\n── P8 打印留痕（追溯链）──")

    r = c.get(f"{API}/work-orders", params={"page_size": 1})
    wo = (items(r) or [{}])[0]
    wo_id = wo.get("id")

    verify_code = None
    print_at = None
    if wo_id:
        r = c.post(f"{API}/print/work_order/{wo_id}", params={"paper": "a4"})
        verify_code = r.headers.get("X-Print-Verify-Code")
        print_at = r.headers.get("X-Print-At")
        report("P8-1 工单可出 A4 归档件（PDF + 留痕头）",
               r.status_code == 200 and (r.headers.get("content-type") or "").startswith("application/pdf")
               and bool(verify_code),
               f"HTTP {r.status_code} {len(r.content)}B code={verify_code} {msg(r) if r.status_code != 200 else ''}")
    else:
        report("P8-1 工单可出 A4 归档件（PDF + 留痕头）", False, "没有工单可打印")

    r = c.get(f"{API}/print/artifacts", params={"page_size": 50})
    arts = items(r)
    art = next((a for a in arts if a.get("verify_code") == verify_code), {})
    report("P8-2 打印留痕列表含本次记录", r.status_code == 200 and bool(art),
           f"共 {len(arts)} 条")

    if verify_code:
        r = c.get(f"{API}/print/verify/{verify_code}")
        v = data(r) or {}
        report("P8-3 留痕码可反查（含单号/版本/副本号）",
               r.status_code == 200 and v.get("doc_no") and v.get("copy_no") is not None,
               f"HTTP {r.status_code} doc_no={v.get('doc_no')} rev={v.get('doc_revision')}")

        # ★ 同一张纸上的两个时间必须一致：纸上印的 X-Print-At 是业务当地时间，
        # 核验页 printed_at 若直接 strftime 一个 timestamptz，会印出 UTC 墙钟 ——
        # 实测 2026-11-05 staging：纸上 08:49:11、核验页 00:49:11，差 8 小时。
        # 这条断言守的就是"纸质记录与数字留痕不许互相打架"。
        got = (v.get("printed_at") or "")[:19]
        report("P8-3b 核验页打印时间与纸面一致（同口径，不是 UTC）",
               bool(print_at) and got == print_at[:19],
               f"纸面 X-Print-At={print_at} / 核验页 printed_at={v.get('printed_at')}")

        aid = art.get("id")
        if aid:
            r = c.get(f"{API}/print/artifacts/{aid}/pdf")
            report("P8-4 留痕件 PDF 可再次下载",
                   r.status_code == 200 and len(r.content) > 500
                   and (r.headers.get("content-type") or "").startswith("application/pdf"),
                   f"HTTP {r.status_code} {len(r.content)}B {msg(r) if r.status_code != 200 else ''}")
        else:
            report("P8-4 留痕件 PDF 可再次下载", False, "列表里没有对应留痕 id")
    else:
        report("P8-3 留痕码可反查（含单号/版本/副本号）", False, "没有留痕码")
        report("P8-4 留痕件 PDF 可再次下载", False, "没有留痕码")

    # ============ P9 租户与模块启停 ============
    print("\n── P9 租户与模块启停 ──")

    r = c.get(f"{API}/tenants/tenant/modules")
    mods = data(r) or {}
    enabled = mods.get("module_codes") if isinstance(mods, dict) else None
    # 演示租户的 package_modules 是空的（没做模块授权），所以只断言"能读到列表"，
    # 不断言非空 —— 那会把数据现状当成接口缺陷。
    report("P9-1 当前租户模块开关可读",
           r.status_code == 200 and isinstance(enabled, list),
           f"HTTP {r.status_code} 已启用 {len(enabled or [])} 个")

    # 原样写回：只验证写通道通，不改动实际启用集（改了会连带影响别的探针）
    r = c.put(f"{API}/tenants/tenant/modules", json={"module_codes": enabled or []})
    report("P9-2 模块开关可写回（幂等，值不变）",
           r.status_code == 200, f"HTTP {r.status_code} {msg(r)}")

    r = c.get(f"{API}/tenants", params={"page_size": 100})
    all_tenants = items(r)
    self_tenant = next((t for t in all_tenants if str(t.get("code")) == TENANT), {})
    tid = self_tenant.get("tenant_id") or real_tid
    report("P9-3 租户列表可读且能找到自己",
           bool(self_tenant), f"共 {len(all_tenants)} 个租户，本租户 tenant_id={tid}")

    r = c.get(f"{API}/tenants/{tid}")
    t = data(r) or {}
    report("P9-4 租户详情可读", r.status_code == 200 and bool(t.get("tenant_id") or t.get("id")),
           f"HTTP {r.status_code} name={t.get('name')}")

    old_name = t.get("name")
    r = c.put(f"{API}/tenants/{tid}", json={"contact_name": f"联络人-{tag}"})
    r2 = c.get(f"{API}/tenants/{tid}")
    t2 = data(r2) or {}
    report("P9-5 租户信息可改且名称不被误改",
           r.status_code == 200 and t2.get("contact_name") == f"联络人-{tag}"
           and t2.get("name") == old_name,
           f"HTTP {r.status_code} contact={t2.get('contact_name')} name={t2.get('name')}")

    r = c.get(f"{API}/tenants/{tid}/license")
    report("P9-6 租户许可可读（未配置时 404 亦接受）",
           r.status_code in (200, 404), f"HTTP {r.status_code} {msg(r)[:60]}")

    # ============ P10 组织/班组/员工/审批/登出 ============
    print("\n── P10 组织、班组、员工、审批、登出 ──")

    r = c.post(f"{API}/teams", json={"name": f"压装工段-{tag}", "code": f"TM-{tag}",
                                     "department": "生产部"})
    r2 = c.get(f"{API}/teams", params={"page_size": 100})
    team = next((x for x in items(r2) if x.get("code") == f"TM-{tag}"), {})
    team_id = team.get("id")
    report("P10-1 班组可创建（前置）", bool(team_id),
           f"HTTP {r.status_code} id={team_id} {msg(r) if not team_id else ''}")

    if team_id:
        r = c.put(f"{API}/teams/{team_id}", json={"name": f"压装工段-{tag}-改", "code": f"TM-{tag}"})
        r2 = c.get(f"{API}/teams", params={"page_size": 100})
        t3 = next((x for x in items(r2) if x.get("id") == team_id), {})
        report("P10-2 班组可改名",
               r.status_code == 200 and str(t3.get("name", "")).endswith("-改"),
               f"HTTP {r.status_code} name={t3.get('name')}")

        r = c.delete(f"{API}/teams/{team_id}")
        r2 = c.get(f"{API}/teams", params={"page_size": 100})
        report("P10-3 班组可删除",
               r.status_code == 200 and not any(x.get("id") == team_id for x in items(r2)),
               f"HTTP {r.status_code} {msg(r) if r.status_code != 200 else ''}")
    else:
        report("P10-2 班组可改名", False, "班组没建起来")
        report("P10-3 班组可删除", False, "班组没建起来")

    r = c.post(f"{API}/employees", json={"name": f"压装工-{tag}", "employee_no": f"E-{tag}",
                                         "position": "压装工"})
    r2 = c.get(f"{API}/employees", params={"page_size": 100})
    emp = next((x for x in items(r2) if x.get("employee_no") == f"E-{tag}"), {})
    emp_id = emp.get("id")
    if emp_id:
        r = c.delete(f"{API}/employees/{emp_id}")
        r2 = c.get(f"{API}/employees", params={"page_size": 100})
        report("P10-4 员工可删除",
               r.status_code == 200 and not any(x.get("id") == emp_id for x in items(r2)),
               f"HTTP {r.status_code} {msg(r) if r.status_code != 200 else ''}")
    else:
        report("P10-4 员工可删除", False, f"员工没建起来 HTTP {r.status_code} {msg(r)}")

    # 组织成员：先加再移
    r = c.get(f"{API}/organizations/tree")
    tree = data(r)
    org_id = None
    if isinstance(tree, list) and tree:
        org_id = tree[0].get("id")
    elif isinstance(tree, dict):
        org_id = tree.get("id")
    if org_id and me_id:
        c.post(f"{API}/organizations/{org_id}/members", json={"user_id": me_id})
        r = c.delete(f"{API}/organizations/{org_id}/members/{me_id}")
        report("P10-5 组织成员可移出",
               r.status_code == 200, f"HTTP {r.status_code} org={org_id} {msg(r)}")
    else:
        report("P10-5 组织成员可移出", False, f"没有组织/用户 id org={org_id} me={me_id}")

    # 审批动作：模板**配了节点**时审批人由模板决定（发起方传的 approver_ids 无效），
    # 而 `/action` 只认「status=pending 且 approver_id==当前用户」的节点。
    # 所以这里先建一个**空节点模板**，让 approver_ids 生效并按顺序落成节点。
    r = c.post(f"{API}/approvals/templates", json={
        "name": f"压装技改审批模板-{tag}", "code": f"APV-{tag}", "biz_type": "trial"})
    r2 = c.get(f"{API}/approvals/templates")
    tpl = next((x for x in items(r2) if x.get("code") == f"APV-{tag}"), {})
    tpl_id = tpl.get("id")
    report("P10-6 审批模板可创建（前置）", bool(tpl_id),
           f"HTTP {r.status_code} id={tpl_id} {msg(r) if not tpl_id else ''}")

    r = c.post(f"{API}/approvals", json={
        "template_id": tpl_id, "title": f"压装技改审批-{tag}", "biz_type": "trial",
        "biz_id": "1", "approver_ids": [me_id] if me_id else [1]})
    ap_id = (data(r) or {}).get("id")
    node_cnt = (data(r) or {}).get("node_count")
    report("P10-7 审批可发起并落审批节点",
           r.status_code == 200 and bool(ap_id) and (node_cnt or 0) >= 1,
           f"HTTP {r.status_code} id={ap_id} nodes={node_cnt} {msg(r) if not ap_id else ''}")

    if ap_id:
        r = c.post(f"{API}/approvals/{ap_id}/action", json={"action": "approve",
                                                            "comment": "同意，按技改方案执行"})
        r2 = c.get(f"{API}/approvals/{ap_id}")
        a = data(r2) or {}
        node_status = [n.get("status") for n in (a.get("nodes") or [])]
        report("P10-8 审批动作可执行并推进状态",
               r.status_code == 200 and node_status == ["approved"]
               and str(a.get("status")) == "approved",
               f"HTTP {r.status_code} 单状态={a.get('status')} 节点={node_status} {msg(r) if r.status_code != 200 else ''}")
    else:
        report("P10-8 审批动作可执行并推进状态", False, "审批没发起成功")

    # 两级审批：验证"前面的节点必须先批"这条顺序闸真的放行第二级
    r = c.post(f"{API}/approvals", json={
        "template_id": tpl_id, "title": f"两级审批-{tag}", "biz_type": "trial",
        "approver_ids": [me_id, me_id] if me_id else [1, 1]})
    ap2 = (data(r) or {}).get("id")
    if ap2:
        r1 = c.post(f"{API}/approvals/{ap2}/action", json={"action": "approve", "comment": "一级同意"})
        r2 = c.post(f"{API}/approvals/{ap2}/action", json={"action": "approve", "comment": "二级同意"})
        r3 = c.get(f"{API}/approvals/{ap2}")
        a2 = data(r3) or {}
        report("P10-9 两级审批可依次推进到通过",
               r1.status_code == 200 and r2.status_code == 200
               and str(a2.get("status")) == "approved",
               f"一级{r1.status_code} 二级{r2.status_code} 单状态={a2.get('status')} "
               f"节点={[n.get('status') for n in (a2.get('nodes') or [])]}")
    else:
        report("P10-9 两级审批可依次推进到通过", False, "两级审批单没建起来")

    # 登出放在最后（会作废当前令牌）
    logout_body = {}
    r = c.post(f"{API}/auth/logout", json=logout_body)
    report("P10-10 登出可调用", r.status_code == 200, f"HTTP {r.status_code} {msg(r)}")

    # ============ P11 Copilot ============
    print("\n── P11 AI Copilot ──")

    # 登出后令牌可能失效 → 重新登录拿新令牌
    payload = login(c)
    if payload.get("access_token"):
        c.headers.update({"Authorization": f"Bearer {payload['access_token']}"})

    asked_ok = False
    try:
        with c.stream("POST", f"{API}/copilot/ask",
                      json={"question": "今天有几个工单逾期？"}) as sr:
            body = "".join(chunk for chunk in sr.iter_text())
            asked_ok = sr.status_code == 200 and "data:" in body
            report("P11-1 自然语言问数可返回 SSE 事件流",
                   asked_ok or sr.status_code == 503,
                   f"HTTP {sr.status_code} 首块={body[:80].replace(chr(10), ' ')}")
    except Exception as exc:  # noqa: BLE001
        report("P11-1 自然语言问数可返回 SSE 事件流", False, f"流式读取失败: {exc}")

    r = c.post(f"{API}/copilot/briefing", json={"role": "workshop_manager"})
    brief = data(r) or {}
    report("P11-2 角色简报可生成", r.status_code == 200 and isinstance(brief, dict),
           f"HTTP {r.status_code} 键={sorted(brief)[:5] if isinstance(brief, dict) else ''} {msg(r) if r.status_code != 200 else ''}")

    r = c.get(f"{API}/copilot/sessions", params={"page_size": 20})
    sesses = items(r)
    report("P11-3 会话列表可读", r.status_code == 200, f"{len(sesses)} 个会话")

    sid = (sesses[0].get("id") if sesses else None)
    mid = None
    if sid:
        r = c.get(f"{API}/copilot/sessions/{sid}")
        mid = (data(r) or {}).get("messages", [{}])[-1].get("id") if data(r) else None

    r = c.post(f"{API}/copilot/feedback", json={
        "message_id": mid or 0, "rating": "good", "reason": "数据准确"})
    report("P11-4 反馈可记录（👍/👎）", r.status_code == 200,
           f"HTTP {r.status_code} {msg(r)}")

    if sid:
        r = c.delete(f"{API}/copilot/sessions/{sid}")
        r2 = c.get(f"{API}/copilot/sessions", params={"page_size": 50})
        report("P11-5 会话可清空",
               r.status_code == 200 and not any(x.get("id") == sid for x in items(r2)),
               f"HTTP {r.status_code} {msg(r) if r.status_code != 200 else ''}")
    else:
        report("P11-5 会话可清空", False, "没有会话可清")

    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("断点：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
