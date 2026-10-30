"""WMS 状态机与过账相关常量（集中定义，禁止在 service/api 内硬编码状态字符串）。

按 ``deliverables/mfg1-n5-architecture-2026-07-12.md`` §3.4 / §7 收敛：
- 入库单状态：pending → inspecting → partially_stored → stored → cancelled
- 出库单状态：pending → approved → picking → partially_issued → issued → cancelled
- 待检区（zone_type='待检'）独立库位行承载；待检区计入现存量、可用量不含（决策#6）。
- 本期只做正向过账 + 取消（cancelled，零库存影响）；红字冲销（reverse）留待下期（决策#1）。
"""
from typing import Dict, List, Tuple

# ============================================
# 入库单状态
# ============================================
RECEIPT_STATUS: List[str] = ["pending", "inspecting", "partially_stored", "stored", "cancelled"]
RECEIPT_PENDING: str = "pending"
RECEIPT_INSPECTING: str = "inspecting"
RECEIPT_PARTIALLY_STORED: str = "partially_stored"
RECEIPT_STORED: str = "stored"
RECEIPT_CANCELLED: str = "cancelled"

# ============================================
# 出库单状态
# ============================================
ISSUE_STATUS: List[str] = ["pending", "approved", "picking", "partially_issued", "issued", "cancelled"]
ISSUE_PENDING: str = "pending"
ISSUE_APPROVED: str = "approved"
ISSUE_PICKING: str = "picking"
ISSUE_PARTIALLY_ISSUED: str = "partially_issued"
ISSUE_ISSUED: str = "issued"
ISSUE_CANCELLED: str = "cancelled"

# ============================================
# 合法状态流转白名单（API / service 层强制校验）
# ============================================
RECEIPT_TRANSITION: Dict[str, List[str]] = {
    RECEIPT_PENDING: [RECEIPT_INSPECTING, RECEIPT_CANCELLED],
    RECEIPT_INSPECTING: [RECEIPT_PARTIALLY_STORED, RECEIPT_STORED, RECEIPT_CANCELLED],
    RECEIPT_PARTIALLY_STORED: [RECEIPT_STORED, RECEIPT_CANCELLED],
    RECEIPT_STORED: [RECEIPT_CANCELLED],
}
ISSUE_TRANSITION: Dict[str, List[str]] = {
    ISSUE_PENDING: [ISSUE_APPROVED, ISSUE_CANCELLED],
    ISSUE_APPROVED: [ISSUE_PICKING, ISSUE_CANCELLED],
    ISSUE_PICKING: [ISSUE_PARTIALLY_ISSUED, ISSUE_ISSUED, ISSUE_CANCELLED],
    ISSUE_PARTIALLY_ISSUED: [ISSUE_ISSUED, ISSUE_CANCELLED],
    ISSUE_ISSUED: [ISSUE_CANCELLED],
}

# 待检区库区类型
ZONE_TYPE_INSPECTION: str = "待检"
# 待检区入库行 inspection_status 取值
INSPECTION_PENDING: str = "待检"
INSPECTION_QUALIFIED: str = "qualified"
INSPECTION_DISQUALIFIED: str = "disqualified"

# 历史遗留同义值：create() 曾写 "pending"，旧数据里还有 NULL。
# 三种写法表达同一个状态，判定前必须先归一，否则闸门只看 disqualified 时
# 会把这些明细当"未检验"一律放行。
_INSPECTION_PENDING_ALIASES = frozenset({"", "pending", "待检", "waiting", "PENDING"})


def normalize_inspection_status(value) -> str:
    """把 inspection_status 归一为 ``待检`` / ``qualified`` / ``disqualified``。

    未知取值原样返回（不猜），以便闸门把它当"无法确认合格"处理。
    """
    if value is None:
        return INSPECTION_PENDING
    text = str(value).strip()
    if text in _INSPECTION_PENDING_ALIASES:
        return INSPECTION_PENDING
    if text.lower() == INSPECTION_QUALIFIED:
        return INSPECTION_QUALIFIED
    if text.lower() == INSPECTION_DISQUALIFIED:
        return INSPECTION_DISQUALIFIED
    return text

# ============================================
# 凭证号规则：MM{yyyymmdd}{seq:04d}（由 repo 在 create 时生成；凭证不可改删）
# ============================================
VOUCHER_RULE: str = "MM{yyyymmdd}{seq:04d}"

# ============================================
# 错误码（与现有 400-0000 风格一致；供 PostingError 使用）
# ============================================
WMS_ERRORS: Dict[str, Tuple[int, str]] = {
    "WMS_409_STATUS": (409, "状态流转非法，当前状态不允许该操作"),
    "WMS_409_NEG_INV": (409, "可用库存不足，无法过账"),
    "WMS_409_INSPECTION": (409, "IQC 未通过，禁止上架确认"),
    "WMS_404_LOCATION": (404, "目标库位不存在"),
    "WMS_409_ALREADY_CANCELLED": (409, "单据已取消，不可重复操作"),
}
