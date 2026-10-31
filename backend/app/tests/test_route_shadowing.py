"""路由遮蔽静态闸（台账 C-53 / C-60）。

FastAPI 按**注册顺序**匹配路由。同一前缀下如果静态段注册在 `{param}` 段之后，
静态段会被当成参数吃掉 —— 请求 `/wms/inventory/by-location` 时 `by-location`
被塞进 `inv_id`，返回 `422 int_parsing`。

这条坑已经踩了**两次**，而且是同一个前缀下的两个兄弟端点：

- C-53：`GET /wms/inventory/by-location` 被 `{inv_id}` 吞噬，100% 422；
- C-60：`GET /wms/inventory/by-material` 一模一样地坏着，当时只修了 by-location，
  **没有顺手扫全**，于是同一处坑留了第二个。

为什么读代码不容易发现：报错是 `422 参数校验`，看起来像调用方传错了参数，
第一反应是去查调用方，而不是查路由注册顺序。

本闸在启动/测试期扫描全部路由：凡某路径的静态段被**同位置更早注册**的
`{param}` 段覆盖，即判失败。新增静态端点时只要放在 `{param}` 前面就不会触发。
"""
import re

import pytest

from app.main import app

_PARAM = re.compile(r"^\{.*\}$")


def _segments(path: str):
    return [s for s in path.split("/") if s]


def find_shadowed_routes():
    """返回 [(被遮蔽的静态路由, 遮蔽它的动态路由)]（按方法去重）。

    判定要够严，否则满屏误报、闸就没人信了：

    1. **段数相同**，且**除某一个位置外其余段字符串完全相同** ——
       只比"某处静态 vs 动态"会把 `/dictionaries/items/{item_id}` 与
       `/dictionaries/{dict_id}/items` 这种**实际不冲突**的组合也算进来
       （后者要求第三段字面等于 items，前者第三段是 id，二者不会互相吃掉）。
    2. **方法有交集** —— FastAPI 匹配的是 (path, method)，方法不符会继续往下找，
       所以 `POST /inventory/stock-move` 与 `GET /inventory/{inv_id}` 并不冲突。
    """
    seen = []          # [(segments, path, methods)]
    problems = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path or not path.startswith("/api"):
            continue
        segs = _segments(path)
        methods = set(getattr(route, "methods", []) or [])
        for prev_segs, prev_path, prev_methods in seen:
            if len(prev_segs) != len(segs) or not (methods & prev_methods):
                continue
            diff = [i for i, (p, s) in enumerate(zip(prev_segs, segs)) if p != s]
            if len(diff) != 1:
                continue
            i = diff[0]
            if _PARAM.match(prev_segs[i]) and not _PARAM.match(segs[i]):
                problems.append((path, prev_path))
        seen.append((segs, path, methods))
    # 去重保序
    uniq = []
    for item in problems:
        if item not in uniq:
            uniq.append(item)
    return uniq


def test_no_static_route_is_shadowed_by_dynamic_segment():
    """同一前缀下，静态段必须注册在 `{param}` 段之前。"""
    problems = find_shadowed_routes()
    assert not problems, (
        "以下静态路由被同位置的 `{param}` 段遮蔽（注册顺序错误，请求会 422）：\n"
        + "\n".join(f"  - {static}  被 {dynamic} 遮蔽" for static, dynamic in problems)
        + "\n修法：把静态端点的声明移到 `{param}` 端点之前。"
    )


@pytest.mark.parametrize("path", [
    "/api/v1/wms/inventory/by-location",
    "/api/v1/wms/inventory/by-material",
])
def test_known_previously_broken_endpoints_are_registered(path):
    """C-53 / C-60 修过的两个端点必须真实存在于路由表里（防回归）。"""
    assert any(getattr(r, "path", None) == path for r in app.routes), (
        f"{path} 不在路由表中")
