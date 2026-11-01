#!/usr/bin/env python3
"""查询参数扫描探针 —— 专治「某个查询参数一传就 500」这一类缺陷。

为什么必须单独有这么一个探针
--------------------------
2026-11-01 staging 回归里，报工列表页整页 500。原因是 `/work-reports`
的 `report_date` 参数被直接以 **'2026-11-01' 字符串** 绑给 `work_reports.report_date`
（DATE 列），asyncpg 严格类型直接拒收：

    invalid input for query argument $1: '2026-11-01' (expected a date, got str)

这类缺陷的可怕之处在于**隐蔽**：
  - SQLite 里字符串能隐式转成 DATE，本地 38 个探针 × 862 条断言全绿；
  - 只有 PostgreSQL 上才炸，而且炸在用户点了某个筛选条件之后；
  - 每个端点都有好几个查询参数，逐个手写探针永远追不上（192 个 GET、
    339 个查询参数）。

所以这里换一种打法：**从 OpenAPI 自动枚举**，把每个端点的每个查询参数
都单独注入一个"形状正确"的样本值，看服务端会不会崩。

判定规则（很关键）
------------------
**只有 HTTP 500 算失败。** 4xx 一律放过 —— 传 `keyword=test`、枚举列传
不认识的值，服务端返回 400/422 是**正确行为**，不是缺陷。把 4xx 算成失败
会让这个探针产生几百条噪音，"满是误报的闸等于没有闸"。

覆盖不到的
----------
本探针只验证「服务端不崩」，不验证「过滤条件真的生效」。后者得靠业务探针
（例如 wms_realistic_e2e 对库存数字逐项对齐）。参数传了但被忽略这种
"静默错误"不在这里管（见 BACKLOG B-17）。

用法
----
    cd backend
    ./.venv/Scripts/python.exe ../e2e/query_param_sweep_e2e.py
    # 打 staging：
    API_BASE=https://mfg1.ziwi.cn/api/v1 ./.venv/Scripts/python.exe ../e2e/query_param_sweep_e2e.py

  SIZE=2000   同时传的最大 page_size（默认 200；见过 page_size 上限改小
              之后 count 查询仍按大值算导致的溢出，留个余量）
  ONLY=xxx    只扫路径里含 xxx 的端点（排查时省时间）
"""

from __future__ import annotations

import os
import sys
import urllib.parse

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
API_ROOT = API[:-len("/api/v1")] if API.endswith("/api/v1") else API

# ★变量名必须带 E2E_ 前缀。用裸 USERNAME 会被 **Windows 系统内置的
#   USERNAME 环境变量**（当前登录名，如 sipon.wu）顶掉 —— 本探针第一版就是
#   这么写的，本地一切正常、一打 staging 就 401「用户名或密码错误」。
#   目录里其它 27 个探针都用 E2E_USER，别自创一套。
USERNAME = os.environ.get("E2E_USER", "mfg_admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin123")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
ONLY = os.environ.get("ONLY", "")

# 每种参数类型给一个"形状正确"的样本。挑值的原则是**尽量让端点真的走到
# 那条 SQL 分支**（否则参数被 if 判空跳过，扫了也是白扫）。
SAMPLE = {
    "date": "2026-11-01",
    "date-time": "2026-11-01T00:00:00",
}
BY_NAME = {
    # 名字里带这些词的，即使 schema 没标 format 也按日期给值
    "_date": "2026-11-01",
    "_at": "2026-11-01T00:00:00",
    "_time": "2026-11-01T00:00:00",
}


def sample_for(name: str, schema: dict):
    """按 schema 优先、名字兜底，给出样本值。"""
    enum = schema.get("enum")
    if enum:
        return enum[0]
    fmt = schema.get("format")
    if fmt in SAMPLE:
        return SAMPLE[fmt]
    for suffix, val in BY_NAME.items():
        if name.endswith(suffix):
            return val
    t = schema.get("type")
    if t == "integer":
        return 1
    if t == "number":
        return 1
    if t == "boolean":
        return "true"
    # 纯字符串参数给个普通值。枚举类列收到不认识的值会 422，那是正常的。
    return "test"


def baseline_params(params: list) -> dict:
    """给每个端点一个安全的底噪：分页压到最小，其它参数一律不传。

    ★不能把所有参数都塞上：某些端点同时传 start_date 和 report_date 会
      在业务层冲突，产生 4xx 噪音，掩盖真正的 500。
    """
    base = {}
    names = {p["name"]: p for p in params}
    if "page" in names:
        base["page"] = 1
    if "page_size" in names:
        base["page_size"] = 5
    return base


def load_spec() -> dict:
    """取 OpenAPI。优先就地导入本地 app（生产环境 /openapi.json 被 SPA 兜底挡住）。

    ★在 staging 上跑时，这份清单来自**本地代码**。若本地比线上新，会请求到
      线上还不存在的端点 → 404，本探针不把 404 算失败，所以不会假红；但反过来
      "线上有、本地没有"的端点会漏扫。做全量回归时应保证本地与线上同 commit。
    """
    try:
        # ★脚本本体在 e2e/ 下，sys.path[0] 是 e2e/ 而不是 cwd，直接
        #   `from app.main import ...` 会 ModuleNotFoundError。探针约定由
        #   run_all.py 以 backend/ 作 cwd 启动，所以把 cwd 显式补进 sys.path。
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())
        from app.main import app  # noqa: PLC0415 — 需要 backend/ 作 cwd
        return app.openapi()
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 本地导入 app 失败（{e}），回退到 HTTP 取 openapi.json")
        r = httpx.get(f"{API_ROOT}/openapi.json", timeout=30)
        if "json" not in (r.headers.get("content-type") or ""):
            # 生产环境 nginx 只反代 /api/v1/*，站点根的 /openapi.json 会被
            # SPA 兜底成 index.html。这时候报 JSONDecodeError 毫无信息量。
            raise RuntimeError(
                f"{API_ROOT}/openapi.json 返回的不是 JSON"
                f"（{r.headers.get('content-type')}，{len(r.content)} 字节）——"
                " 多半被前端 SPA 兜底了。请确保能 `from app.main import app`。"
            )
        return r.json()


def main() -> int:
    spec = load_spec()
    paths = spec.get("paths", {})

    with httpx.Client(timeout=60, follow_redirects=False) as c:
        r = c.post(f"{API}/auth/login",
                   json={"username": USERNAME, "password": PASSWORD, "tenant_id": TENANT})
        if r.status_code != 200:
            print(f"[FATAL] 登录失败 {r.status_code}: {r.text[:200]}")
            return 2
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

        targets = []
        for path, ops in sorted(paths.items()):
            op = ops.get("get")
            if not op:
                continue
            if ONLY and ONLY not in path:
                continue
            params = [p for p in op.get("parameters", []) if p.get("in") == "query"]
            url_path = path
            # 路径参数一律替换成 1：拿不到真实 id 时 404 很正常，不算失败，
            # 但"id=1 就崩"是真缺陷，值得看。
            while "{" in url_path:
                head, _, rest = url_path.partition("{")
                _, _, tail = rest.partition("}")
                url_path = head + "1" + tail
            targets.append((path, url_path, params))

        print(f"== 查询参数扫描：{len(targets)} 个 GET 端点  base={API} ==")

        ok = bad = 0
        failures = []
        not_found = 0

        for path, url_path, params in targets:
            base = baseline_params(params)

            # ① 底噪：不带任何业务参数先打一次。这里就 500 说明端点本身坏了
            #    （跟参数无关），单独记一类，避免归因错。
            #    ★URL 用 API_ROOT + path：OpenAPI 里的 path **已经含 /api/v1 前缀**
            #      （如 /api/v1/work-reports）。第一版写成 API + path，拼出
            #      /api/v1/api/v1/... 全 404，而 404 不计失败 → 388 项"全绿"，
            #      实际一个端点都没打到。这种"永远绿的门禁"比没有门禁更危险。
            try:
                rr = c.get(f"{API_ROOT}{url_path}", params=base)
            except Exception as e:  # noqa: BLE001
                ok += 1
                print(f"  [ERR ] {path} 连接异常 {e}")
                continue
            if rr.status_code == 404:
                not_found += 1
            if rr.status_code >= 500:
                bad += 1
                failures.append((path, "(无参数)", rr.status_code, _rid(rr)))
                print(f"  [FAIL] {path} 底噪即 {rr.status_code} rid={_rid(rr)}")
                continue
            ok += 1

            # ② 逐个参数：底噪 + 这一个参数
            for p in params:
                name = p["name"]
                schema = p.get("schema", {}) or {}
                # page / page_size 已在底噪里，跳过，避免重复打
                if name in ("page", "page_size"):
                    continue
                q = dict(base)
                q[name] = sample_for(name, schema)
                qs = urllib.parse.urlencode(q, doseq=True)
                try:
                    rr = c.get(f"{API_ROOT}{url_path}?{qs}")
                except Exception as e:  # noqa: BLE001
                    ok += 1
                    print(f"  [ERR ] {path}?{name}= 连接异常 {e}")
                    continue
                if rr.status_code >= 500:
                    bad += 1
                    failures.append((path, f"{name}={q[name]}", rr.status_code, _rid(rr)))
                    print(f"  [FAIL] {path}?{name}={q[name]} → {rr.status_code} rid={_rid(rr)}")
                else:
                    ok += 1

    print("\n" + "=" * 64)
    # ★护栏：底噪大面积 404 说明地址拼错/环境不对，此时"全绿"是假的。
    #   没有这道判据，探针会在扫到 0 个真实端点的情况下报 PASS。
    if targets and not_found * 2 > len(targets):
        print(f"[FATAL] {not_found}/{len(targets)} 个端点底噪返回 404 —— "
              f"地址前缀大概率拼错（检查 API_BASE 与 OpenAPI path 是否重复带 /api/v1）")
        print(f"汇总：通 {ok} / 断 {max(bad, 1)}")
        print("=" * 64)
        return 2
    if failures:
        print("失败清单（只有 5xx 计入）：")
        for path, which, st, rid in failures:
            print(f"  - {path}  [{which}]  HTTP {st}  request_id={rid}")
        print("  ★拿 request_id 去后端日志对栈："
              "docker logs mfg1-backend 2>&1 | grep <request_id>")
    print(f"汇总：通 {ok} / 断 {bad}")
    print("=" * 64)
    return 0 if bad == 0 else 1


def _rid(resp) -> str:
    try:
        return resp.json().get("request_id", "-")
    except Exception:  # noqa: BLE001
        return "-"


if __name__ == "__main__":
    sys.exit(main())
