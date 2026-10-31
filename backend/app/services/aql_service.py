"""GB/T 2828.1（= ISO 2859-1 / ANSI Z1.4）计数抽样方案引擎。

为什么要有它
------------
清单 D-S7 标 ❌「缺抽样规则」：此前**全库没有任何抽样方案代码**，
``qc_point_config.sampling_plan`` 只是一串自由文本（种子里写着 ``AQL=1.0``），
检验员拿到手里的只有「抽 5 个看看」这种口头经验，抽多少、允收几个不合格
全凭人定 —— 同一批货两个人抽检能得出相反结论，且无法追溯依据。

本模块把「批量 → 样本量字码 → 样本量 + 允收数 Ac / 拒收数 Re」这一步
变成**可查表、可复算、可写进检验单留痕**的确定性结果。

数据来源与校验
--------------
表 1（样本量字码）与表 2-A（正常检验一次抽样主表）是**公开标准**，
本模块的数据经四个独立来源交叉核对后录入：
  - Eurofins《Product Inspection AQL》poster（含箭头 ↑↓）
  - inspectionservice.com《AQL Tables Explained》示例
  - aqmbd.com《Acceptable Quality Level》Ac/Re 表
  - tyaward / qc-easy 抽样表
测试里固化了六条**外部可核对的锚点**（如「批量 3000 / 水平 II / AQL 2.5
→ 抽 125、允收 7、拒收 8」），改坏了会立刻红。

★为什么不把标准表放进数据库
----------------------------
它是**标准，不是租户配置** —— 放进库里每个租户一份，改坏一处就静默产出
错误的样本量，而这种错误**肉眼绝对看不出来**（抽 50 还是抽 80 都像回事）。
放代码里则可以被单元测试锚死。真正属于租户配置的是「这个检验点用哪个
AQL、哪个检验水平」，那部分仍落在 ``qc_point_config.sampling_plan``。

★箭头（↑↓）必须实现，不能填死数值
----------------------------------
主表里相当一部分格子不是数值而是箭头，含义是「这一格没有对应方案，
改用**箭头方向的第一个方案**」（↓ 向下 = 更大的样本；↑ 向上 = 更小的样本）。
早期我打算照着网上简化的「速查表」把每格都填成数字，但那些速查表彼此
冲突（同一格差一两列），且**填死之后就看不出「这一格其实没有方案」** ——
正好是最危险的那种静默错误。这里如实保留箭头，查表时按标准规则解析，
并在结果里回带 ``arrow`` 字段说明"这个方案是从哪一格沿箭头取来的"。

范围
----
只做**正常检验、一次抽样**。加严/放宽检验属于转移规则（标准第 9 条），
依赖连续批次的验收历史，不在本轮范围（见 BACKLOG）。
"""
from typing import Dict, List, Optional, Tuple

# 箭头：主表里"本格无方案，改用箭头方向第一个方案"
DOWN = "↓"   # 向下 = 样本量更大的那一格
UP = "↑"     # 向上 = 样本量更小的那一格

# 支持的 AQL 档位（制造业实际在用的区间：致命 0（全检）、
# 严重 1.0/2.5、轻微 4.0/6.5；医药/汽车会用到 0.40/0.65）
AQL_LEVELS: List[float] = [0.40, 0.65, 1.0, 1.5, 2.5, 4.0, 6.5]

# 支持的检验水平：一般 I/II/III + 特殊 S-1~S-4（破坏性试验用小样本）
INSPECTION_LEVELS = ["S-1", "S-2", "S-3", "S-4", "I", "II", "III"]
DEFAULT_LEVEL = "II"

# ── 表 1：批量 × 检验水平 → 样本量字码 ──────────────────────
# (批量下限, 批量上限 or None 表示不限, {水平: 字码})
_SAMPLE_SIZE_CODE: List[Tuple[int, Optional[int], Dict[str, str]]] = [
    (2, 8,           {"S-1": "A", "S-2": "A", "S-3": "A", "S-4": "A",
                      "I": "A", "II": "A", "III": "B"}),
    (9, 15,          {"S-1": "A", "S-2": "A", "S-3": "A", "S-4": "A",
                      "I": "A", "II": "B", "III": "C"}),
    (16, 25,         {"S-1": "A", "S-2": "A", "S-3": "B", "S-4": "B",
                      "I": "B", "II": "C", "III": "D"}),
    (26, 50,         {"S-1": "A", "S-2": "B", "S-3": "B", "S-4": "C",
                      "I": "C", "II": "D", "III": "E"}),
    (51, 90,         {"S-1": "B", "S-2": "B", "S-3": "C", "S-4": "C",
                      "I": "C", "II": "E", "III": "F"}),
    (91, 150,        {"S-1": "B", "S-2": "B", "S-3": "C", "S-4": "D",
                      "I": "D", "II": "F", "III": "G"}),
    (151, 280,       {"S-1": "B", "S-2": "C", "S-3": "D", "S-4": "E",
                      "I": "E", "II": "G", "III": "H"}),
    (281, 500,       {"S-1": "B", "S-2": "C", "S-3": "D", "S-4": "E",
                      "I": "F", "II": "H", "III": "J"}),
    (501, 1200,      {"S-1": "C", "S-2": "C", "S-3": "E", "S-4": "F",
                      "I": "G", "II": "J", "III": "K"}),
    (1201, 3200,     {"S-1": "C", "S-2": "D", "S-3": "E", "S-4": "G",
                      "I": "H", "II": "K", "III": "L"}),
    (3201, 10000,    {"S-1": "C", "S-2": "D", "S-3": "F", "S-4": "G",
                      "I": "J", "II": "L", "III": "M"}),
    (10001, 35000,   {"S-1": "C", "S-2": "D", "S-3": "F", "S-4": "H",
                      "I": "K", "II": "M", "III": "N"}),
    (35001, 150000,  {"S-1": "D", "S-2": "E", "S-3": "G", "S-4": "H",
                      "I": "L", "II": "N", "III": "P"}),
    (150001, 500000, {"S-1": "D", "S-2": "E", "S-3": "G", "S-4": "J",
                      "I": "M", "II": "P", "III": "Q"}),
    (500001, None,   {"S-1": "D", "S-2": "E", "S-3": "H", "S-4": "K",
                      "I": "N", "II": "Q", "III": "R"}),
]

# ── 字码 → 样本量 ──────────────────────────────────────────
CODE_SAMPLE_SIZE: Dict[str, int] = {
    "A": 2, "B": 3, "C": 5, "D": 8, "E": 13, "F": 20, "G": 32, "H": 50,
    "J": 80, "K": 125, "L": 200, "M": 315, "N": 500, "P": 800,
    "Q": 1250, "R": 2000,
}
# 顺序即"样本量由小到大"，箭头解析靠它找上下相邻格
CODE_ORDER: List[str] = ["A", "B", "C", "D", "E", "F", "G", "H",
                         "J", "K", "L", "M", "N", "P", "Q", "R"]

# ── 表 2-A：正常检验一次抽样主表 ────────────────────────────
# 每行按 AQL_LEVELS 的顺序给 7 个格子；格子可以是 (Ac, Re) 元组，
# 也可以是 DOWN / UP 箭头。注意 **没有字母 I 和 O**（标准里刻意跳过，
# 避免与数字 1、0 混淆）。
_MASTER: Dict[str, List] = {
    "A": [DOWN, DOWN, DOWN, DOWN, DOWN, DOWN, (0, 1)],
    "B": [DOWN, DOWN, DOWN, DOWN, DOWN, (0, 1), UP],
    "C": [DOWN, DOWN, DOWN, DOWN, (0, 1), UP, DOWN],
    "D": [DOWN, DOWN, DOWN, (0, 1), UP, DOWN, (1, 2)],
    "E": [DOWN, DOWN, (0, 1), UP, DOWN, (1, 2), (2, 3)],
    "F": [DOWN, (0, 1), UP, DOWN, (1, 2), (2, 3), (3, 4)],
    "G": [(0, 1), UP, DOWN, (1, 2), (2, 3), (3, 4), (5, 6)],
    "H": [UP, DOWN, (1, 2), (2, 3), (3, 4), (5, 6), (7, 8)],
    "J": [DOWN, (1, 2), (2, 3), (3, 4), (5, 6), (7, 8), (10, 11)],
    "K": [(1, 2), (2, 3), (3, 4), (5, 6), (7, 8), (10, 11), (14, 15)],
    "L": [(2, 3), (3, 4), (5, 6), (7, 8), (10, 11), (14, 15), (21, 22)],
    "M": [(3, 4), (5, 6), (7, 8), (10, 11), (14, 15), (21, 22), UP],
    "N": [(5, 6), (7, 8), (10, 11), (14, 15), (21, 22), UP, UP],
    "P": [(7, 8), (10, 11), (14, 15), (21, 22), UP, UP, UP],
    "Q": [(10, 11), (14, 15), (21, 22), UP, UP, UP, UP],
    "R": [(14, 15), (21, 22), UP, UP, UP, UP, UP],
}


class AqlError(ValueError):
    """抽样方案查不出来。一律显式抛出，绝不返回"看起来合理"的默认值 ——

    静默给一个错误的样本量，比直接说"这个组合我不会"危险得多：
    检验员会照着错的样本量去抽，且永远发现不了。
    """


def normalize_level(level: Optional[str]) -> str:
    """检验水平归一化：``ii`` / ``2`` / ``general_ii`` → ``II``。"""
    if not level:
        return DEFAULT_LEVEL
    s = str(level).strip().upper().replace("GENERAL_", "")
    if s in ("2", "II", "GII"):
        return "II"
    if s in ("1", "I"):
        return "I"
    if s in ("3", "III"):
        return "III"
    if s.startswith("S"):
        s2 = s.replace("S-", "S").replace("S", "S-", 1)
        if s2 in INSPECTION_LEVELS:
            return s2
    if s in INSPECTION_LEVELS:
        return s
    raise AqlError(f"不支持的检验水平：{level}（可选 {INSPECTION_LEVELS}）")


def normalize_aql(aql) -> float:
    """AQL 归一化：字符串 ``"1.0"`` / ``"AQL=2.5"`` → ``2.5``。"""
    if aql is None:
        raise AqlError("缺少 AQL 值")
    if isinstance(aql, str):
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", aql)
        if not m:
            raise AqlError(f"无法从 {aql!r} 解析出 AQL 数值")
        aql = m.group(1)
    try:
        val = float(aql)
    except (TypeError, ValueError):
        raise AqlError(f"无法从 {aql!r} 解析出 AQL 数值")
    # 浮点不能直接 in 列表比较（1.0 与 1 相等但 0.4+0.25 之类会有误差）
    for lv in AQL_LEVELS:
        if abs(val - lv) < 1e-9:
            return lv
    raise AqlError(
        f"不支持的 AQL：{val}（已内置档位 {AQL_LEVELS}；"
        f"如需其它档位请按 GB/T 2828.1 扩充主表）")


def code_letter(lot_qty: int, level: Optional[str] = None) -> str:
    """批量 + 检验水平 → 样本量字码（表 1）。"""
    lv = normalize_level(level)
    if lot_qty is None or lot_qty < 1:
        raise AqlError(f"批量必须为正整数，收到 {lot_qty}")
    lot_qty = int(lot_qty)
    if lot_qty < 2:
        # 标准表最小批量是 2；批量为 1 时只能全检
        raise AqlError(f"批量 {lot_qty} 小于抽样表最小批量 2，请直接全检")
    for lo, hi, mapping in _SAMPLE_SIZE_CODE:
        if lot_qty >= lo and (hi is None or lot_qty <= hi):
            return mapping[lv]
    raise AqlError(f"批量 {lot_qty} 未落在抽样表任何区间内")


def _resolve(code: str, aql_idx: int) -> Tuple[str, int, int, Optional[str]]:
    """沿箭头解析出真正的方案。

    返回 ``(最终字码, ac, re, 箭头说明 or None)``。
    ★必须带步数上限：万一主表被改错成互相指向的环，这里会死循环。
    """
    steps = 0
    arrow_note = None
    while steps <= len(CODE_ORDER):
        cell = _MASTER[code][aql_idx]
        if isinstance(cell, tuple):
            return code, cell[0], cell[1], arrow_note
        idx = CODE_ORDER.index(code)
        nxt = idx + 1 if cell == DOWN else idx - 1
        if nxt < 0 or nxt >= len(CODE_ORDER):
            raise AqlError(
                f"抽样表箭头越界：字码 {code} / AQL {AQL_LEVELS[aql_idx]} "
                f"（标准表数据有误，请核对主表）")
        arrow_note = (arrow_note or
                      f"字码 {code} 在 AQL {AQL_LEVELS[aql_idx]} 无对应方案，"
                      f"按标准改用{'下方（样本量更大）' if cell == DOWN else '上方（样本量更小）'}第一个方案")
        code = CODE_ORDER[nxt]
        steps += 1
    raise AqlError(
        f"抽样表箭头解析超过 {len(CODE_ORDER)} 步仍未落到数值方案"
        f"（起始字码 {code} / AQL {AQL_LEVELS[aql_idx]}，疑似主表成环）")


def plan(lot_qty: int, aql, level: Optional[str] = None) -> Dict:
    """按批量 + AQL + 检验水平给出完整抽样方案。

    返回字段里除了 ``sample_qty / ac / re``，还刻意回带
    ``code_letter / resolved_code / arrow / full_inspection``：
    **结论必须可复算** —— 检验员或审核员拿到"抽 50 个、最多允收 3 个"时，
    得能追出"它是从批量 500 / 水平 II / AQL 2.5 查来的"，否则一旦有争议
    只能靠翻标准书重新算一遍。
    """
    lv = normalize_level(level)
    aql_v = normalize_aql(aql)
    aql_idx = AQL_LEVELS.index(aql_v)
    cl = code_letter(lot_qty, lv)
    resolved, ac, re, arrow = _resolve(cl, aql_idx)
    sample_qty = CODE_SAMPLE_SIZE[resolved]

    result = {
        "lot_qty": int(lot_qty),
        "aql": aql_v,
        "level": lv,
        "code_letter": cl,
        "resolved_code": resolved,
        "sample_qty": sample_qty,
        "ac": ac,
        "re": re,
        "arrow": arrow,
        "full_inspection": False,
        "standard": "GB/T 2828.1 (ISO 2859-1) 正常检验 一次抽样",
    }

    # ★标准的硬规则：样本量 ≥ 批量时做 100% 检验，不再是"抽样"。
    # 少了这一步会出现"批量 20、方案要抽 32 个"这种荒谬指令。
    if sample_qty >= int(lot_qty):
        result.update({
            "sample_qty": int(lot_qty),
            "ac": 0,
            "re": 1,
            "full_inspection": True,
            "arrow": (arrow + "；" if arrow else "") +
                     f"样本量 {sample_qty} ≥ 批量 {int(lot_qty)}，按标准改为 100% 全检",
        })
    return result


def verdict(defect_count: int, ac: int, re: int) -> str:
    """不合格数 → 判定。``ACC``（≤ Ac）/ ``REJ``（≥ Re）。"""
    if defect_count is None:
        raise AqlError("缺少不合格数")
    d = int(defect_count)
    if d <= int(ac):
        return "ACC"
    if d >= int(re):
        return "REJ"
    # Ac 与 Re 在标准里恒差 1，落到这段说明数据被改坏了
    raise AqlError(f"不合格数 {d} 落在 Ac={ac} 与 Re={re} 之间的空档（标准里不应存在）")


def parse_sampling_plan(text) -> Optional[float]:
    """从 ``qc_point_config.sampling_plan`` 的自由文本里解出 AQL。

    支持 ``AQL=1.0`` / ``aql 2.5`` / ``AQL1.0`` / ``1.0``；解不出返回 None
    （**不抛**）—— 检验点的抽样方案是可选配置，没配不该让建检验单失败，
    只是退化成"没有抽样方案、样本数由人工填"。
    """
    if not text:
        return None
    import re
    m = re.search(r"AQL\s*[=:：]?\s*(\d+(?:\.\d+)?)", str(text), re.IGNORECASE)
    if not m:
        return None
    try:
        return normalize_aql(m.group(1))
    except AqlError:
        return None
