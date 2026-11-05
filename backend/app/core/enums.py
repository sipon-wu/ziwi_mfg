"""工序类型（`operations.op_type`）值域 —— 后端唯一真源。

## 为什么值得单开一个文件

2026-11-05 查 staging 时发现同一份值域被复制了**三份**，且没有一份和库里对得上：

| 位置 | 内容 |
|---|---|
| `models/basic_data.py` 的列注释 | 11 个值，一个 `*_qc` 都没有 |
| `frontend/.../OperationList.vue::OP_TYPE_OPTIONS` | 同样 11 个（从注释抄的） |
| `frontend/src/config/searchFields.ts::OP_TYPE` | 又同样 11 个（第二份副本） |
| **库里实际存在** | 上面 11 个 + `incoming_qc` / `process_qc` / `final_qc`，外加脏值 `production` |

后果三条，都是用户直接看得见的：

1. 「工序类型」列对未知值 `|| v` 兜底 → 页面上直接印英文原文 `process_qc`；
2. 编辑弹窗的下拉里没有当前值 → 用户一保存就把类型改成别的（静默改数据）；
3. 接口对 `op_type` 零校验 → 探针把 `route_steps.step_type` 的 `production`
   塞进了 `op_type`，`mfg_demo` 里 65 条工序全成了 `production`。

**`production` 不属于这里**：它是 `route_steps.step_type`（production/inspect/
outsource）的值，两列语义不同，混用是探针写错，不是值域不够。

## 约定

- 后端以本文件为真源；写入端用 `OpType`（`Literal`）校验，非法值由 FastAPI 出 422。
- 前端以 `frontend/src/config/enums.ts` 为真源。
- 两侧一致性由 `app/tests/test_op_type_domain.py` 读前端常量文件断言，
  任一侧改了而另一侧没跟，测试立刻红。
"""
from typing import Literal, get_args

# 代码 → 中文标签。**顺序即前端下拉顺序**：先加工/装配等主类型，
# 再把三种检验（来料/过程/终检）排在一起 —— 车间按检验阶段找，不按字母找。
OP_TYPE_LABELS: dict[str, str] = {
    "machining": "机加工",
    "assembly": "装配",
    "heat_treat": "热处理",
    "surface_treat": "表面处理",
    "inspect": "检验",
    "incoming_qc": "来料检",
    "process_qc": "过程检",
    "final_qc": "终检",
    "pack": "包装",
    "reaction": "反应",
    "blend": "混合",
    "separation": "分离",
    "filling": "灌装",
    "transport": "转运",
}

OP_TYPES: tuple[str, ...] = tuple(OP_TYPE_LABELS)

#: Pydantic 用的字面量类型：`op_type: OpType` → 非法值 422。
OpType = Literal[*OP_TYPE_LABELS]


def op_type_label(code: str | None) -> str:
    """代码转中文；未知值给「未知」而不是回显英文原文。

    后端目前没有出口用到它，留着是为了将来导出/打印别各写一份 ``|| code``
    （前端那个兜底正是这么漏的）。
    """
    if not code:
        return ""
    return OP_TYPE_LABELS.get(code, f"未知（{code}）")


# 自检：`OpType` 必须与 `OP_TYPE_LABELS` 同步（`Literal[*d]` 取的是 dict 的 key，
# 但 dict 将来被改成非 dict 或插入非 str 时要在导入期就炸，而不是等 422 文案变怪）。
assert set(get_args(OpType)) == set(OP_TYPE_LABELS), "OpType 与 OP_TYPE_LABELS 不同步"
assert all(isinstance(k, str) for k in OP_TYPES), "op_type 只能是字符串"
