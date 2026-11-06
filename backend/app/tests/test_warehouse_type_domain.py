"""仓库类型（`warehouses.type`）值域一致性闸。

## 这个测试要挡什么

`warehouses.type` 此前**没有任何真源**：模型列注释写 4 个值，前端
`WarehouseTree.vue` 另有一份 4 项硬编码字典，接口对它零校验。
实测库里 7 个值，其中 3 个是别名（`raw` / `wip` / `finished_goods`）、
2 个是声明域里根本没有但业务真实存在的（`line_side` 线边仓、
`spare_parts` 备件仓）。

用户侧可见后果有两条：

1. 线边仓 / 备件仓在仓库树上直接印英文原码（硬编码字典里没有这两个键）；
2. `production_service` 完工入库按 `type='finished'` 找仓，若租户建的是
   `finished_goods`，就变成"没有成品仓" —— 半成品与成品混仓，全程不报错。

所以本文件守四条：
1. 后端 `WarehouseType`（Literal）与 `WAREHOUSE_TYPE_LABELS` 自洽；
2. 别名表的目标值都在域内，且别名键不能同时是合法值（否则归一规则自相矛盾）；
3. 前端 `enums.ts::WAREHOUSE_TYPE_OPTIONS` 与后端**逐项且同序**一致；
4. 写入 schema 真的归一并拒绝域外值（不是"注释里写了"）。
"""
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.core.enums import (
    WAREHOUSE_TYPE_ALIASES,
    WAREHOUSE_TYPE_LABELS,
    WAREHOUSE_TYPES,
    WarehouseType,
    normalize_warehouse_type,
    warehouse_type_label,
)
from app.schemas.wms import WarehouseCreate, WarehouseUpdate

# backend/app/tests/x.py → parents[3] = 仓库 code/ 根
FRONTEND_ENUMS = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "config" / "enums.ts"
)


# ── 1. 后端自洽 ────────────────────────────────────────────────

def test_literal_matches_label_map():
    assert set(get_args(WarehouseType)) == set(WAREHOUSE_TYPE_LABELS)
    assert tuple(get_args(WarehouseType)) == WAREHOUSE_TYPES


def test_business_types_are_present():
    """线边仓与备件仓必须在域内。

    这两个值库里真有、业务上也不能合并（不同物理区域）。少了任何一个，
    接口就会把现存仓库判成非法，或者界面上只能印英文原码。
    """
    for code in ("line_side", "spare_parts"):
        assert code in WAREHOUSE_TYPE_LABELS, f"{code} 缺失，该类仓无法用中文表达"


def test_aliases_target_inside_domain():
    """别名必须指向域内值，且别名键不能同时是合法值。

    前者错了会把数据搬进一个非法值里（比不迁移更糟）；后者错了说明
    归一规则自相矛盾（同一个码既当别名又当规范值）。
    """
    assert set(WAREHOUSE_TYPE_ALIASES.values()) <= set(WAREHOUSE_TYPE_LABELS)
    assert not (set(WAREHOUSE_TYPE_ALIASES) & set(WAREHOUSE_TYPE_LABELS))


def test_three_legacy_aliases_mapped():
    """实测库里的三个别名一个都不能漏 —— 漏一个就是一类仓永远找不到。"""
    assert normalize_warehouse_type("raw") == "raw_material"
    assert normalize_warehouse_type("wip") == "semi"
    assert normalize_warehouse_type("finished_goods") == "finished"


def test_unknown_label_does_not_echo_raw_code():
    assert warehouse_type_label("line_side") == "线边仓"
    assert warehouse_type_label("abc") == "未知（abc）"
    assert warehouse_type_label(None) == ""


# ── 2. 跨语言一致（前端单一真源）────────────────────────────────

def _frontend_options() -> list[tuple[str, str]]:
    """从 `enums.ts` 抽出 `WAREHOUSE_TYPE_OPTIONS` 的 (value, label) 序列。"""
    text = FRONTEND_ENUMS.read_text(encoding="utf-8")
    m = re.search(
        r"export const WAREHOUSE_TYPE_OPTIONS\s*:\s*EnumOption\[\]\s*=\s*\[(.*?)\n\]",
        text, re.S,
    )
    assert m, f"在 {FRONTEND_ENUMS} 里找不到 WAREHOUSE_TYPE_OPTIONS 定义"
    pairs = re.findall(
        r"\{\s*value:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'\s*\}", m.group(1)
    )
    assert pairs, "WAREHOUSE_TYPE_OPTIONS 里一个 { value, label } 都没解析到"
    return pairs


def test_frontend_matches_backend_exactly():
    """逐项同序。顺序是契约：它就是下拉框顺序（物流方向）。"""
    fe = _frontend_options()
    be = list(WAREHOUSE_TYPE_LABELS.items())
    assert [p[0] for p in fe] == [p[0] for p in be], (
        "前端 WAREHOUSE_TYPE_OPTIONS 与后端 WAREHOUSE_TYPE_LABELS 代码序列不一致")
    assert fe == be, "代码一致但中文标签不一致（同一个值两种叫法）"


def test_frontend_does_not_redefine_labels():
    """`LABEL_DICT.warehouse_type` 必须是**从 options 推出来的**。

    再手写一份就等于又有两个真源 —— 那正是这次要修的病根。
    """
    text = FRONTEND_ENUMS.read_text(encoding="utf-8")
    assert "LABEL_DICT.warehouse_type = Object.fromEntries" in text, (
        "warehouse_type 标签表应派生自 WAREHOUSE_TYPE_OPTIONS，不要另写一份")


# ── 3. 写入校验真的生效 ────────────────────────────────────────

def test_create_normalizes_alias():
    """历史别名要能继续写入，但落库是规范值（不能把脏值再存一遍）。"""
    assert WarehouseCreate(code="W1", name="一号库", type="raw").type == "raw_material"
    assert WarehouseCreate(code="W1", name="一号库", type="wip").type == "semi"
    assert (WarehouseCreate(code="W1", name="一号库", type="finished_goods").type
            == "finished")


def test_create_defaults_to_raw_material():
    assert WarehouseCreate(code="W1", name="一号库").type == "raw_material"


def test_create_rejects_unknown_type_with_legal_values_in_message():
    with pytest.raises(ValidationError) as ei:
        WarehouseCreate(code="W1", name="一号库", type="warehouse")
    # 报错里要能看到合法取值，否则前端只能干瞪眼
    assert "半成品仓" in str(ei.value)


def test_update_allows_omitted_but_rejects_invalid():
    """更新时空缺表示"不改这个字段"，不能被当成非法值拒掉。"""
    assert WarehouseUpdate(name="改名").type is None
    with pytest.raises(ValidationError):
        WarehouseUpdate(type="warehouse")
