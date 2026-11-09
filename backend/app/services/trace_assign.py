#!/usr/bin/env python3
"""报工触发的部件码自动赋码 —— 方案书 §2.1 的前两个赋码节点。

## 方案书怎么说的

| 层级 | 对象 | 赋码规则 | 赋码节点 |
|:--|:--|:--|:--|
| 一级部件码 | 定子 | `TD-YYYYMMDD-流水号` | 工序1 `CW010` 槽绝缘插入 |
| 一级部件码 | 转子 | `TZ-YYYYMMDD-流水号` | 工序7 `RT010` 转子保持架压装 |
| 二级成品码 | 整机 | `TC-YYYYMMDD-流水号` | 工序13 `MA020` 合装 |

第三个节点由 `BatchService.compose`（扫定子码 + 扫转子码当场合码）实现；
前两个此前只能有人去批次管理页手敲一条（台账 B-30），就是本模块补的。

## 三个口径，都定在这里，不散落在调用点

**1）触发点 = 报工提交即赋码，不等打印确认。**
报工就是「这道工序完工了」的事实记录，码是这件活的标识；打印是随后的动作。
让"打印机在线"成为追溯链的前置条件，等于打印机一离线整条链就断 ——
而这恰恰是追溯最该工作的时刻（停线返工、补打标签）。

**2）节点是数据，不是代码。**
哪道工序出哪个码，配在字典 `trace_code_node`（item_code = 规则键，
item_value = 工序编码）。方案书按工序编码写（`CW010` / `RT010`），换一条
产线工序编码就变，写死在代码里等于把这一家的工艺卡刻进平台。

**3）一件一码。**
`output_qty = N` 就出 N 个码。部件码是贴在一件实物上的，一批共用一码
等于放弃单件追溯 —— 而「定子 + 转子 → 整机」的追溯本来就要求一台整机
对应一个唯一的定子码。

## 刻意不做「成品码」

`REPORT_ASSIGNABLE_RULES` 只有 `wip_stator` / `wip_rotor`。即使有人在字典里
给 `final` 配了工序，这里也**不认**（`match_node` 显式过滤）。

理由：成品码在合装工位扫码合成，一台整机一个码。报工再出一个，同一台整机
就有两个长得一模一样的码 —— 一个空号、一个真码，现场分不出该贴哪个，
追溯按码查直接劈叉。

## 失败不许阻断报工

报工是既成事实（活已经干完了），赋码出不来是主数据/配置问题，不该让车间
完不了工 —— 与 `_raise_production_receipt`（完工入库单建不出来只说明原因）
同一口径。所有异常在这里吞掉并转成 `warnings` 上抛，由报工响应带出去。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.core.business_time import business_today
from app.core.trace_code import (
    RULE_LABELS,
    REPORT_ASSIGNABLE_RULES,
    TRACE_NODE_DICT_CODE,
    TRACE_RULE_DICT_CODE,
    code_prefix_pattern,
    compose_code,
    resolve_prefix,
    seq_of,
)

#: 单次报工最多出多少个码。
#
# 一件一码意味着 `output_qty=500` 就要建 500 行 —— 这是对的，不是 bug。
# 但报工数量是手填的，多打一个零就会瞬间灌进十万行并把事务拖死。
# 超过这个数就不自动出码、只给一句可执行的提示（分批报工，或走补码），
# 而不是替现场把一次误敲变成十万行垃圾数据。
MAX_CODES_PER_REPORT = 200


async def load_trace_dict(repo, dict_code: str) -> Dict[str, str]:
    """读一张追溯字典 → `{item_code: item_value}`。

    字典没建 / 没配项 / 项被停用，一律返回空 dict。**不预置任何客户值**：
    预置等于替客户拍板，猜错了比空着更难查（见 `core/trace_code.py` 模块注释）。

    任何异常都吞成空 dict —— 字典不可用不该让报工挂掉。

    ⚠️ 走 `DictionaryRepository.list_items` 而不是基类 `query()`：
       `dictionary_items` 表**没有 tenant_id 列**，基类会给它注入
       `tenant_id = :_tenant_id` → `no such column` → 500。
    """
    from app.repositories.dictionary_repo import DictionaryRepository

    try:
        dr = DictionaryRepository(repo._session).inherit_context_from(repo)
        d = await dr.get_dict_by_code(dict_code)
        if not d:
            return {}
        items = await dr.list_items(d["id"])
    except Exception:  # noqa: BLE001 — 字典读不到只是"没法赋码"，不是报工失败
        return {}

    out: Dict[str, str] = {}
    for it in items or []:
        code = (it.get("item_code") or "").strip()
        val = (it.get("item_value") or "").strip()
        if code and val and (it.get("status") or "active") == "active":
            out[code] = val
    return out


def match_node(nodes: Dict[str, str] | None, operation_code: str) -> Optional[str]:
    """工序编码 → 规则键。匹配不到返回 `None`。

    - 大小写与首尾空白不敏感（现场导入的工序编码常带空格）
    - **只认 `REPORT_ASSIGNABLE_RULES` 里的规则**：字典里即使给 `final`
      配了节点也过滤掉，理由见模块 docstring（一台整机两个码）
    """
    op = (operation_code or "").strip().upper()
    if not op or not nodes:
        return None
    for rule, node_op in nodes.items():
        if rule not in REPORT_ASSIGNABLE_RULES:
            continue
        if (node_op or "").strip().upper() == op:
            return rule
    return None


async def assign_for_report(repo, *, tenant_id: str, order: dict, report_id: int,
                            operation_code: str, qty: int) -> dict:
    """按报工产出赋部件码。

    **业务上不抛异常**：节点没配、工序不匹配、物料没建档、产出为 0，全部
    走 `skipped + reason` 返回，由调用方决定要不要提示（见模块 docstring
    「失败不许阻断报工」）。

    唯一例外是 `IntegrityError`（并发撞号）—— 那一种**必须让整笔报工回滚**：
    继续往前走会提交一个「报工进了、码没出」的半截状态，比整笔失败更难查。
    异常原样上抛，由 `ProductionService.create_report` 转成可重试的 400。

    返回::

        {
          "assigned": int,          # 实际出了几个码
          "rule": str | None,       # 命中的规则键
          "label": str,             # 规则中文名（提示文案用）
          "codes": [{batch_id, batch_no}],
          "skipped": bool,
          "reason": str,            # 没赋码时说清为什么（正常路径也可能为空）
          "prefix_source": str,     # dict / fallback
          "warnings": [str],        # 需要让人看见的事
        }
    """
    out = {"assigned": 0, "rule": None, "label": "", "codes": [],
           "skipped": True, "reason": "", "prefix_source": "dict",
           "warnings": []}

    if qty <= 0:
        out["reason"] = "产出数为 0，没有需要赋码的对象"
        return out

    nodes = await load_trace_dict(repo, TRACE_NODE_DICT_CODE)
    if not nodes:
        # 绝大多数租户没配这张字典 —— 这是**正常状态**，不是异常，
        # 不能每次报工都往 warnings 里塞一条提示（那会让警告栏变成噪音，
        # 真该看的告警被淹掉）。
        out["reason"] = "未配置赋码节点（字典 trace_code_node），不自动出码"
        return out

    rule = match_node(nodes, operation_code)
    if not rule:
        out["reason"] = "该工序不是赋码节点"
        return out

    label = RULE_LABELS.get(rule, rule)
    out["rule"] = rule
    out["label"] = label

    from app.repositories.wms_repo import BatchRepository

    brepo = BatchRepository(repo._session).inherit_context_from(repo)

    # ── 幂等：同一次报工只赋一次码 ──────────────────────────────
    already = await brepo.query_one(
        "SELECT COUNT(*) AS n FROM batches WHERE source_report_id = :r",
        {"r": report_id},
    )
    if int((already or {}).get("n") or 0) > 0:
        out["reason"] = "该报工已赋过码（重复提交，不重复出码）"
        return out

    # ── 物料：用**工单产品**，不是随手一个成品物料 ────────────────
    # 定子工单的产品就是定子总成（SP-AH-STATOR），转子同理。
    wo = await brepo.resolve_final_material(order.get("id"))
    if not wo or not wo.get("material_id"):
        out["reason"] = (
            f"工单产品「{order.get('product_code')}」未在物料主数据建档，"
            f"{label}无法生成（生成的码进不了库存）")
        out["warnings"].append(out["reason"])
        return out

    if qty > MAX_CODES_PER_REPORT:
        out["reason"] = (
            f"本次产出 {qty} 件，超过单次自动赋码上限 {MAX_CODES_PER_REPORT} 件，"
            f"未自动生成{label}；请分批报工（每批不超过 {MAX_CODES_PER_REPORT} 件）")
        out["warnings"].append(out["reason"])
        return out

    rules = await load_trace_dict(repo, TRACE_RULE_DICT_CODE)
    prefix, prefix_source = resolve_prefix(rules, rule)
    out["prefix_source"] = prefix_source
    if prefix_source == "fallback":
        # 兜底必须显形（同 compose）：码照样出得来、标签照样打得出来，
        # 但形态不合客户规格，等主机厂 MES 解析失败才发现就晚了。
        out["warnings"].append(
            f"{label}前缀未在字典 trace_code_rule 配置，当前用兜底前缀「{prefix}」，"
            f"码形与方案书不一致，请让管理员补配置")

    today = business_today().isoformat()
    latest = await brepo.latest_no(code_prefix_pattern(prefix, today))
    seq = (seq_of(latest) or 0) + 1

    for i in range(qty):
        batch_no = compose_code(prefix, today, seq + i)
        new_id = await brepo.create({
            "tenant_id": tenant_id,
            "batch_no": batch_no,
            "material_id": wo["material_id"],
            "status": "active",
            "batch_type": "wip",
            "source_report_id": report_id,
        })
        out["codes"].append({"batch_id": new_id, "batch_no": batch_no})

    out["assigned"] = len(out["codes"])
    out["skipped"] = False
    return out
