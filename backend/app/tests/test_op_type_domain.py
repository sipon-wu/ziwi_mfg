"""工序类型（`operations.op_type`）值域一致性闸。

## 这个测试要挡什么

2026-11-05 在 staging 上查得同一份值域被散成三份、三份都和库里对不上：

- 模型列注释：11 个值
- `OperationList.vue::OP_TYPE_OPTIONS`：11 个值（抄注释）
- `searchFields.ts::OP_TYPE`：11 个值（再抄一份）
- 库里实际：上面 11 个 + `incoming_qc` / `process_qc` / `final_qc` + 脏值 `production`

用户侧可见后果：艾华推进器场景的工序（`process_qc`/`final_qc`）在列表里
「类型」列直接印英文原文；编辑弹窗下拉里没有当前值，一保存就把类型改掉。

所以本文件守三条：
1. 后端 `OpType`（Literal）与 `OP_TYPE_LABELS` 自洽；
2. 前端 `enums.ts::OP_TYPE_OPTIONS` 与后端**逐项且同序**一致（跨语言闸）；
3. 写入 schema 对非法值真的报错（不是"注释里写了"）。
"""
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.core.enums import OP_TYPE_LABELS, OP_TYPES, OpType, op_type_label
from app.schemas.basic_data import OperationCreate, OperationUpdate

# backend/app/tests/x.py → parents[3] = 仓库 code/ 根
FRONTEND_ENUMS = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "config" / "enums.ts"
)


# ── 1. 后端自洽 ────────────────────────────────────────────────

def test_literal_matches_label_map():
    """Literal 的成员必须与标签表完全一致，不能一边加了另一边忘。"""
    assert set(get_args(OpType)) == set(OP_TYPE_LABELS)
    assert tuple(get_args(OpType)) == OP_TYPES


def test_qc_stages_are_present():
    """三种检验阶段必须在值域里 —— 这是艾华方案书明确区分的口径。

    少了任何一个，推进器场景的来料检/过程检/终检工序就无法用中文类型表达，
    只能退回 `inspect`，把三段检验糊成一个。
    """
    for code in ("incoming_qc", "process_qc", "final_qc"):
        assert code in OP_TYPE_LABELS, f"{code} 缺失，检验阶段会被糊成 inspect"


def test_production_is_not_a_valid_op_type():
    """`production` 是 `route_steps.step_type` 的值，不是工序类型。

    探针曾把它塞进 `op_type`，在 mfg_demo 攒下 65 条垃圾工序；接口加了
    Literal 校验后这类写入必须直接失败，而不是静默落库。
    """
    assert "production" not in OP_TYPE_LABELS


def test_unknown_label_does_not_echo_raw_code():
    """未知值给「未知（原文）」，不能只回原文 —— 否则脏数据看着像正常值。"""
    assert op_type_label("process_qc") == "过程检"
    assert op_type_label("production") == "未知（production）"
    assert op_type_label(None) == ""


# ── 2. 跨语言一致（前端单一真源）────────────────────────────────

def _frontend_options() -> list[tuple[str, str]]:
    """从 `enums.ts` 抽出 `OP_TYPE_OPTIONS` 的 (value, label) 序列。"""
    text = FRONTEND_ENUMS.read_text(encoding="utf-8")
    m = re.search(
        r"export const OP_TYPE_OPTIONS\s*:\s*EnumOption\[\]\s*=\s*\[(.*?)\n\]",
        text, re.S,
    )
    assert m, f"在 {FRONTEND_ENUMS} 里找不到 OP_TYPE_OPTIONS 定义"
    body = m.group(1)
    pairs = re.findall(
        r"\{\s*value:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'\s*\}", body
    )
    assert pairs, "OP_TYPE_OPTIONS 里一个 { value, label } 都没解析到"
    return pairs


def test_frontend_matches_backend_exactly():
    """前后端值域必须**逐项同序**一致。

    顺序也是契约：`OP_TYPE_LABELS` 的插入序就是下拉框顺序，两边都这么写着。
    只比集合会放过"前端多一个、后端少一个"这种情况。
    """
    fe = _frontend_options()
    be = list(OP_TYPE_LABELS.items())
    assert [p[0] for p in fe] == [p[0] for p in be], (
        "前端 OP_TYPE_OPTIONS 与后端 OP_TYPE_LABELS 的代码序列不一致")
    assert fe == be, "代码一致但中文标签不一致（同一个值两种叫法）"


# ── 3. 写入校验真的生效 ────────────────────────────────────────

def test_create_rejects_step_type_leak():
    with pytest.raises(ValidationError) as ei:
        OperationCreate(code="OP1", name="下料", op_type="production")
    # 报错里要能看到合法取值，否则前端只能干瞪眼
    assert "process_qc" in str(ei.value)


def test_create_accepts_qc_stages():
    for code in ("incoming_qc", "process_qc", "final_qc"):
        op = OperationCreate(code="OP1", name="定子电检", op_type=code)
        assert op.op_type == code


def test_update_rejects_invalid_but_allows_omitted():
    """更新时空缺表示"不改这个字段"，不能被当成非法值拒掉。"""
    assert OperationUpdate(name="改名").op_type is None
    with pytest.raises(ValidationError):
        OperationUpdate(op_type="production")
