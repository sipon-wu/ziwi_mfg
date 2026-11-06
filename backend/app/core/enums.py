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

# ══════════════════════════════════════════════════════════════════
# 工作中心类别（`work_centers.wc_type`）—— 后端唯一真源
#
# ## 这个字段历史上是"三份各说各话"
#
# | 位置 | 内容 |
# |---|---|
# | `models/basic_data.py` 列注释 | `production_line` / `work_cell` / `workstation`（粒度）|
# | `frontend/.../WorkCenterList.vue::WC_TYPE_OPTIONS` | 同样 3 个（抄注释）|
# | `frontend/src/config/searchFields.ts::WC_TYPE` | 又同样 3 个（第二份副本）|
# | **库里实际** | 艾华 33 个工位全是 `assembly`(19) / `quality`(9) / `machining`(5) —— **一个粒度值都没有** |
#
# 于是列表「类型」列 33/33 行裸渲染英文，而「产线 / 工作单元」两个选项
# 全库**零使用**（是照着那句注释凭空建的）。
#
# ## ★ 它混了两种正交语义 —— 这里如实承认，不再假装只有一个
#
# ① **粒度**：产线 / 工作单元 / 工位。`work_centers` 表本身就是这一层的单元；
#    探针建工位时填 `workstation`，说明这个语义真在用。
# ② **工艺性质**：这个工作中心主要承担什么工艺（机加工 / 装配 / 热处理…）。
#    艾华的实际数据全在这一维。
#
# 不拆成两个字段的理由：拆要给 33 行数据做归因（工位到底"是工位"还是"是装配"，
# 两个答案都对），而当前没有任何计算按 wc_type 分支 —— 它只做等值筛选与展示。
# 拆字段是产品决策，不是一次数据清理能定的。所以先把**值域收到一处、加闸看住**。
#
# ## 为什么不直接 `= OP_TYPE_LABELS`
#
# - 工序的检验被细分成 来料检/过程检/终检 三段；一个**工作中心**在物理空间上
#   只分"检验工位"，不分工序阶段 → 这里用单个 `quality`，不铺开四段。
# - `reaction` / `blend` / `separation` / `filling` / `transport` 属流程行业，
#   本项目边界已明确排除 → 不列，免得下拉里全是永远用不到的值。
# - 断言闸 (`test_wc_type_domain.py`) 把"比 OP_TYPE 多出来的值"钉死在白名单
#   4 个上：`quality` / `production_line` / `work_cell` / `workstation`。
#   多一个就红 —— 防止再有人往这里塞野值。
# ══════════════════════════════════════════════════════════════════
WC_TYPE_LABELS: dict[str, str] = {
    # ── 粒度（顺序即下拉顺序：先"这个东西有多大"，再"它干什么活"）──
    "production_line": "产线",
    "work_cell": "工作单元",
    "workstation": "工位",
    # ── 工艺性质 ──
    "machining": "机加工",
    "assembly": "装配",
    "heat_treat": "热处理",
    "surface_treat": "表面处理",
    "quality": "检验",
    "pack": "包装",
}

WC_TYPES: tuple[str, ...] = tuple(WC_TYPE_LABELS)

#: Pydantic 用的字面量类型：`wc_type: WcType` → 非法值 422。
WcType = Literal[*WC_TYPE_LABELS]


def wc_type_label(code: str | None) -> str:
    """代码转中文；未知值给「未知（原文）」，不回显原文冒充正常值。"""
    if not code:
        return ""
    return WC_TYPE_LABELS.get(code, f"未知（{code}）")


#: `WC_TYPE_LABELS` 允许超出 `OP_TYPE_LABELS` 的值（白名单，多一个就红）。
#: 每一条都要能说出理由，否则就是野值。
WC_TYPE_EXTRA_ALLOWED: frozenset[str] = frozenset({
    "production_line", "work_cell", "workstation",  # 粒度语义
    "quality",                                      # 工作中心粒度的"检验"
})

assert set(get_args(WcType)) == set(WC_TYPE_LABELS), \
    "WcType 与 WC_TYPE_LABELS 不同步"
assert set(WC_TYPE_LABELS) - set(OP_TYPE_LABELS) == WC_TYPE_EXTRA_ALLOWED, (
    "WC_TYPE_LABELS 比 OP_TYPE_LABELS 多出的值必须恰好是白名单那一组；"
    "新增值请先在 WC_TYPE_EXTRA_ALLOWED 里写明理由"
)


# ── 工艺性质（从工序派生，不落库） ────────────────────────────────
#: 「这个工位在干什么活」。它是 `OP_TYPE_LABELS` 的**归一结果**：
#: 4 种检验（inspect / incoming_qc / process_qc / final_qc）在这个维度上是
#: 同一件事，合成 `quality`；其余类型自成一类。
#:
#: ★ 为什么单独一张表，不直接借 `WC_TYPE_LABELS`：
#:   `WC_TYPE_LABELS` 是工作中心**档案字段**的写入值域（混了粒度与工艺性质），
#:   而工艺性质是派生的。两者一旦共用一张表，往任一方向加值都会污染另一边。
#:   曾经试过借用，结果 `filling`（灌装）派生出来在 wc_type 表里查不到 →
#:   界面显示「未知（filling）」，语义修好了却修出个"未知"。
PROCESS_NATURE_LABELS: dict[str, str] = {
    "machining": "机加工",
    "assembly": "装配",
    "heat_treat": "热处理",
    "surface_treat": "表面处理",
    "quality": "检验",
    "pack": "包装",
    "reaction": "反应",
    "blend": "混合",
    "separation": "分离",
    "filling": "灌装",
    "transport": "转运",
}

PROCESS_NATURES: tuple[str, ...] = tuple(PROCESS_NATURE_LABELS)

ProcessNature = Literal[*PROCESS_NATURE_LABELS]


def nature_label(code: str | None) -> str:
    """工艺性质转中文；未知值给「未知（原文）」。"""
    if not code:
        return ""
    return PROCESS_NATURE_LABELS.get(code, f"未知（{code}）")


#: 归一后必须全部可渲染 —— 派生出一个没有中文标签的值，界面就只能印「未知」。
NATURE_UNMAPPED: frozenset[str] = frozenset(
    {"inspect", "incoming_qc", "process_qc", "final_qc"}
)
assert set(PROCESS_NATURE_LABELS) == (set(OP_TYPE_LABELS) - NATURE_UNMAPPED) | {"quality"}, (
    "PROCESS_NATURE_LABELS 必须是 OP_TYPE_LABELS 把 4 种检验归一成 quality 的结果；"
    "新增工序类型时这里要同步，否则界面会出现「未知（xxx）」"
)


# ── 洁净度等级（工序「环」要素里的无尘度） ──────────────────────────
#: 存储码用 ``isoN``（ISO 14644-1 等级号，与 GB/T 25915 一致），中文名按车间口头
#: 习惯把「X 级」放在前面、ISO 号放括号里 —— 客户说的是"万级"、"十万级"，
#: 不是"ISO 7"。渲染出来的必须是客户能对上话的那几个字。
#:
#: ★ 为什么要有 ``none``（无洁净要求）：
#:   它区分的是「评估过，确实不需要」和「压根没填」。两者在无尘车间排产、
#:   工序外协判定里是完全不同的结论，混成一个"空"就永远分不清。
#:
#: ★ 为什么不只给万级/十万级两个"常用值"：
#:   这是**客户报什么就得存什么**的客观属性，不是我们替客户归并的主观分类。
#:   值域收窄的唯一后果是客户报了百级，我们只能往十万级塞 —— 数据当场失真。
CLEAN_LEVEL_LABELS: dict[str, str] = {
    "none": "无洁净要求",
    "iso5": "百级（ISO 5）",
    "iso6": "千级（ISO 6）",
    "iso7": "万级（ISO 7）",
    "iso8": "十万级（ISO 8）",
    "iso9": "三十万级（ISO 9）",
}

CLEAN_LEVELS: tuple[str, ...] = tuple(CLEAN_LEVEL_LABELS)

CleanLevel = Literal[*CLEAN_LEVEL_LABELS]


def clean_level_label(code: str | None) -> str:
    """洁净度等级转中文；未知值给「未知（原文）」，不回显原文冒充正常值。"""
    if not code:
        return ""
    return CLEAN_LEVEL_LABELS.get(code, f"未知（{code}）")

