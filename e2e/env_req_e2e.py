"""工序「环」要素（洁净度/温度/湿度）端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/env_req_e2e.py

本地要显式指租户（本地 ``mfg_admin`` 属 ``mfg_demo``，staging 才是 ``AH-THR``）::

    E2E_TENANT=mfg_demo ../backend/.venv/Scripts/python.exe e2e/env_req_e2e.py

覆盖场景：

    ENV-1  建带环境要求的工序 → 读回是对象（不是 JSON 字符串）
    ENV-2  平铺 ``clean_level`` 已物化（高级检索靠它，客户端求值只认平铺 key）
    ENV-3  局部更新（不带 env_req）不得清空环境要求
    ENV-4  改洁净度 → 整条环境要求被替换（不是逐键 merge）
    ENV-5  显式置 null → 干净清空
    ENV-6  非法值全部 422（湿度越界 / 下限>上限 / 值域外的洁净度码）
    ENV-7  库里已有的**旧自由文本**读回来落进 ``legacy_text``，不静默丢弃
    ENV-8  ``legacy_text`` 可原样回写（一次保存不会把旧数据改成 JSON）
    ENV-9  收尾：自建工序删干净

★ 为什么这条探针必须存在
  ``env_req`` 此前是 ``Optional[str]`` 自由文本、页面无输入框，全库 0 条有值 ——
  也就是说"读回是字符串"这个缺陷**没有任何数据能暴露它**。单测只能断言源码里
  调了 ``encode_env_req``，只有真打一遍 HTTP 才能证明链路是通的。
"""
import os
import sys
import time

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def main() -> int:
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code}（本地请设 E2E_TENANT=mfg_demo）")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})

    tag = time.strftime("%m%d%H%M%S")
    code = f"OP-ENV-{tag}"
    op_id = None
    base = {
        "code": code,
        "name": "环要素探针工序",
        "op_type": "assembly",
        "env_req": {
            "clean_level": "iso8",
            "temp_min": 20,
            "temp_max": 26,
            "humidity_min": 45,
            "humidity_max": 60,
        },
    }

    try:
        r = c.post(f"{API}/operations", json=base)
        check("ENV-1a 建带环境要求的工序", r.status_code == 200,
              f"{r.status_code} {r.text[:120]}")
        op_id = ((r.json().get("data") or {}).get("id"))

        d = c.get(f"{API}/operations/{op_id}").json()["data"]
        env = d.get("env_req")
        check("ENV-1b 读回是对象而非 JSON 字符串",
              isinstance(env, dict), f"{type(env).__name__}")
        check("ENV-1c 洁净度值正确",
              (env or {}).get("clean_level") == "iso8", str(env))
        check("ENV-2  平铺 clean_level 已物化",
              d.get("clean_level") == "iso8", str(d.get("clean_level")))

        # 列表出口也得是对象 —— 列表和详情是两条代码路径
        items = c.get(f"{API}/operations", params={
            "page": 1, "page_size": 50, "keyword": code}).json()["data"]["items"]
        check("ENV-2b 列表出口同样是对象",
              bool(items) and isinstance(items[0].get("env_req"), dict),
              f"{len(items)} 条")

        r = c.put(f"{API}/operations/{op_id}", json={"remark": "只改备注"})
        env = c.get(f"{API}/operations/{op_id}").json()["data"].get("env_req") or {}
        check("ENV-3  局部更新不清空环境要求",
              r.status_code == 200 and env.get("clean_level") == "iso8", str(env))

        r = c.put(f"{API}/operations/{op_id}", json={
            "env_req": {"clean_level": "iso7", "temp_min": 22, "temp_max": 24}})
        env = c.get(f"{API}/operations/{op_id}").json()["data"].get("env_req") or {}
        check("ENV-4  改洁净度是整条替换（旧湿度不留）",
              r.status_code == 200 and env.get("clean_level") == "iso7"
              and env.get("humidity_min") is None, str(env))

        r = c.put(f"{API}/operations/{op_id}", json={"env_req": None})
        d = c.get(f"{API}/operations/{op_id}").json()["data"]
        check("ENV-5  显式置 null 可清空",
              r.status_code == 200 and d.get("env_req") is None
              and d.get("clean_level") is None, str(d.get("env_req")))

        for name, bad in (
            ("ENV-6a 湿度 120 被拒", {"humidity_max": 120}),
            ("ENV-6b 温度下限>上限被拒", {"temp_min": 30, "temp_max": 20}),
            ("ENV-6c 值域外洁净度码被拒", {"clean_level": "万级"}),
        ):
            rr = c.post(f"{API}/operations", json={**base, "code": f"{code}-X", "env_req": bad})
            check(name, rr.status_code == 422, str(rr.status_code))

        # 旧自由文本：只能从写入口之外造（当前 API 已经把自由文本收进 legacy_text，
        # 但历史数据里可能直接是裸文本）—— 这里用"送自由文本"来覆盖解码分支
        r = c.put(f"{API}/operations/{op_id}", json={"env_req": "温控 20-25℃，湿度≤60%"})
        env = c.get(f"{API}/operations/{op_id}").json()["data"].get("env_req") or {}
        check("ENV-7a 旧自由文本不丢（收进 legacy_text）",
              env.get("legacy_text") == "温控 20-25℃，湿度≤60%", str(env))
        check("ENV-7b 旧文本不被误认成洁净度",
              env.get("clean_level") is None, str(env))
        r = c.put(f"{API}/operations/{op_id}", json={"env_req": env})
        env2 = c.get(f"{API}/operations/{op_id}").json()["data"].get("env_req") or {}
        check("ENV-8  legacy_text 可原样回写",
              env2.get("legacy_text") == "温控 20-25℃，湿度≤60%", str(env2))

    finally:
        if op_id:
            rr = c.delete(f"{API}/operations/{op_id}")
            left = c.get(f"{API}/operations", params={
                "page": 1, "page_size": 50, "keyword": f"OP-ENV-{tag}"}).json()["data"]["total"]
            check("ENV-9  自建工序已清理（不留垃圾给产能闸）",
                  rr.status_code == 200 and left == 0, f"残留 {left}")

    print(f"\n{len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        print("失败：" + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
