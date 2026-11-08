"""`/wms/reports/summary` 的契约守卫（B-17）。

为什么单独一个文件、且只断言 OpenAPI schema
-------------------------------------------
这个端点的问题是**参数收下但不生效**，而不是返回错的值：

    start_date / end_date 声明了，实现从头到尾没读过；
    调用方传了区间以为在查历史，实际拿到的永远是「此刻」。

这类缺陷没法用「返回对不对」来测 —— 数字本身是对的，错的是**它宣称能做什么**。
最省事又能防回归的判据是看**接口签名**：只要参数不在 schema 里，就没有人能
误以为区间生效。

★ 为什么不能靠代码走查：参数长得像正常入参，SQL 里也完全合法地不引用它，
  两者单看都没毛病。2026-11-01 就登记过，一直没人看出问题。
"""

from __future__ import annotations

from app.main import app


def _summary_params() -> dict:
    """取 `/wms/reports/summary` 的 query 参数名集合。"""
    schema = app.openapi()
    # 路径前缀由部署决定（容器里带 /api/v1，本地未必），按后缀找而不是写死。
    key = next(
        (p for p in schema["paths"] if p.endswith("/wms/reports/summary")),
        None,
    )
    assert key is not None, f"OpenAPI 里找不到该端点，实际路径：{sorted(schema['paths'])}"
    params = schema["paths"][key]["get"].get("parameters") or []
    return {p["name"] for p in params}


def test_summary_does_not_claim_date_range():
    """端点不得再声明 start_date / end_date。

    这两个参数曾被声明却从不读取 —— 传了不报错、结果永远是当前快照，
    是最容易让对账对不上的形态（口径错但不报错）。
    真要支持区间收支，必须另开独立端点并把「收入/发出各含哪些单据类型」
    先与业务确认，不能在这个端点里悄悄补两个参数了事。
    """
    names = _summary_params()
    assert "start_date" not in names, f"start_date 又回到 schema 里了：{sorted(names)}"
    assert "end_date" not in names, f"end_date 又回到 schema 里了：{sorted(names)}"


def test_summary_keeps_warehouse_filter():
    """warehouse_id 是**真实生效**的筛选，不能顺手删掉。

    与上面两条相反的方向：删参数时容易把真正在用的那个一起删。
    这里钉住「至少还留着 warehouse_id」，防止过度清理。
    """
    names = _summary_params()
    assert "warehouse_id" in names, f"warehouse_id 被误删了：{sorted(names)}"
