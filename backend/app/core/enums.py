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


# ══════════════════════════════════════════════════════════════════
# 仓库类型（`warehouses.type`）值域 —— 后端唯一真源
#
# 这个值域此前**只活在一句列注释里**（`comment="raw_material/semi/finished/
# consumable"`），没有任何校验、没有枚举、前端另有一份 4 项硬编码字典。
# 结果库里实际躺着 7 个值，其中 3 个是别名或脏值：
#
#   声明域      raw_material  semi        finished   consumable
#   库内实际    raw           wip         finished_goods       ← 别名，指的同一件事
#               line_side     spare_parts                      ← 真实存在、声明域里却没有
#
# 危害不是"不好看"，而是**按类型找仓库的代码会静默找不到**：
# 生产入库要取 `type='finished'` 的仓，而有租户建的是 `finished_goods` ——
# 于是"没有成品仓"，半成品/成品混仓，全程不报错。
#
# ## 域怎么定的
#
# 以**业务真有**为准，不以旧注释为准：保留 `line_side`（线边仓）与
# `spare_parts`（备件仓），因为它们是不同物理区域，语义不能合并；
# 三个同义别名一律归一到声明域（`raw`→`raw_material`、`wip`→`semi`、
# `finished_goods`→`finished`）。
#
# 顺序 = 物流方向：原料进厂 → 线边 → 在制/半成品 → 成品 → 备件/耗材。
# ══════════════════════════════════════════════════════════════════
WAREHOUSE_TYPE_LABELS: dict[str, str] = {
    "raw_material": "原料仓",
    "line_side": "线边仓",
    "semi": "半成品仓",
    "finished": "成品仓",
    "spare_parts": "备件仓",
    "consumable": "耗材仓",
}

WAREHOUSE_TYPES: tuple[str, ...] = tuple(WAREHOUSE_TYPE_LABELS)

#: Pydantic 用的字面量类型：`type: WarehouseType` → 非法值 422。
WarehouseType = Literal[*WAREHOUSE_TYPE_LABELS]

#: 历史别名 → 规范值。迁移脚本与写入归一共用同一张表，避免两处各写一份。
WAREHOUSE_TYPE_ALIASES: dict[str, str] = {
    "raw": "raw_material",
    "wip": "semi",
    "finished_goods": "finished",
}


def warehouse_type_label(code: str | None) -> str:
    """代码转中文；未知值给「未知（原文）」，不回显原文冒充正常值。"""
    if not code:
        return ""
    return WAREHOUSE_TYPE_LABELS.get(code, f"未知（{code}）")


def normalize_warehouse_type(code: str | None) -> str | None:
    """把历史别名归一成规范值；空值原样返回。

    只做别名映射，**不**把未知值硬塞成默认值 —— 未知就是未知，交给校验去拒。
    """
    if code is None:
        return None
    key = code.strip()
    return WAREHOUSE_TYPE_ALIASES.get(key, key)


assert set(get_args(WarehouseType)) == set(WAREHOUSE_TYPE_LABELS), \
    "WarehouseType 与 WAREHOUSE_TYPE_LABELS 不同步"
# 别名必须指向域内值，否则迁移会把数据搬进一个非法值里（比不迁移更糟）
assert set(WAREHOUSE_TYPE_ALIASES.values()) <= set(WAREHOUSE_TYPE_LABELS), \
    "WAREHOUSE_TYPE_ALIASES 的目标值必须都在值域内"
assert not (set(WAREHOUSE_TYPE_ALIASES) & set(WAREHOUSE_TYPE_LABELS)), \
    "别名键不能同时是合法值，否则归一规则自相矛盾"
