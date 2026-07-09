"""
SPC 统计计算引擎 — 纯 Python 实现，无 NumPy 依赖。

包含：
- X̄-R 控制图计算
- p/np 控制图计算
- 过程能力分析（Cp/Cpk/Pp/Ppk）
- Nelson 判异规则（7种）
- 系数表（A2/D3/D4 for n=2~10）
"""
import math
import json
from typing import List, Dict, Optional, Tuple

# ── 控制图系数表 (n=2~10) ──────────────────────────────────────
_A2_TABLE = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483,
             7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
_D3_TABLE = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
_D4_TABLE = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114, 6: 2.004,
             7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}


def _mean(values: List[float]) -> float:
    """计算平均值"""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stdev(values: List[float]) -> float:
    """计算样本标准差（无偏估计，ddof=1）"""
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    variance = sum((x - avg) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _get_coefficients(n: int) -> Tuple[float, float, float]:
    """获取 A2/D3/D4 系数"""
    a2 = _A2_TABLE.get(n, 0.577)   # default n=5
    d3 = _D3_TABLE.get(n, 0)
    d4 = _D4_TABLE.get(n, 2.114)   # default n=5
    return a2, d3, d4


# ── 公开 API ───────────────────────────────────────────────────

def calculate_xbar_r(
    product_id: int, process_id: int, check_item: int,
    raw_data: List[Dict], subgroup_size: int = 5,
) -> dict:
    """X̄-R 控制图计算

    Args:
        product_id: 产品ID
        process_id: 工序ID
        check_item: 检验项目ID
        raw_data: 原始数据列表 [{"measured_value": "12.3", ...}]
        subgroup_size: 子组大小（默认n=5）

    Returns:
        {"points": [...], "limits": {...}, "anomalies": [...]}
    """
    # 提取数值
    values = []
    for row in raw_data:
        try:
            v = float(row.get("measured_value", ""))
            values.append(v)
        except (ValueError, TypeError):
            continue

    if len(values) < subgroup_size:
        return {"points": [], "limits": None, "anomalies": [], "error": "数据点不足，无法生成子组"}

    # 按子组分组
    subgroups = []
    for i in range(0, len(values), subgroup_size):
        group = values[i:i + subgroup_size]
        if len(group) == subgroup_size:
            subgroups.append(group)

    if len(subgroups) < 2:
        return {"points": [], "limits": None, "anomalies": [], "error": "子组数不足（至少需要2组）"}

    # 计算每子组 x̄ 和 R
    points = []
    for idx, group in enumerate(subgroups):
        xbar = _mean(group)
        r = max(group) - min(group)
        points.append({
            "subgroup_no": idx + 1,
            "sample_values": json.dumps(group),
            "xbar": round(xbar, 4),
            "r": round(r, 4),
        })

    # 计算总体均值 (x̄̄) 和平均极差 (R̄)
    xbar_values = [p["xbar"] for p in points]
    r_values = [p["r"] for p in points]
    grand_mean = _mean(xbar_values)
    r_bar = _mean(r_values)

    # 查系数表
    n = subgroup_size
    a2, d3, d4 = _get_coefficients(n)

    # X̄ 图控制限
    cl_x = round(grand_mean, 4)
    ucl_x = round(grand_mean + a2 * r_bar, 4)
    lcl_x = round(grand_mean - a2 * r_bar, 4)

    # R 图控制限
    cl_r = round(r_bar, 4)
    ucl_r = round(d4 * r_bar, 4)
    lcl_r = round(d3 * r_bar, 4)

    limits = {
        "chart_type": "xbar_r",
        "xbar": {"cl": cl_x, "ucl": ucl_x, "lcl": lcl_x},
        "r": {"cl": cl_r, "ucl": ucl_r, "lcl": lcl_r},
        "subgroup_count": len(subgroups),
        "grand_mean": grand_mean,
        "r_bar": r_bar,
    }

    # 应用判异规则检测异常点
    anomalies = []
    for point in points:
        triggered = nelson_rules({
            "xbar": point["xbar"],
            "r": point["r"],
        }, xbar_values, limits)

        if triggered:
            point["is_anomaly"] = True
            point["anomaly_rules"] = json.dumps([t["rule_no"] for t in triggered])
            anomalies.extend(triggered)
        else:
            point["is_anomaly"] = False
            point["anomaly_rules"] = "[]"

    return {"points": points, "limits": limits, "anomalies": anomalies, "error": None}


def calculate_p_np(
    product_id: int, process_id: int, check_item: int,
    raw_data: List[Dict],
) -> dict:
    """p/np 控制图计算

    Args:
        raw_data: [{ "result": "ACC"/"REJ" }]
    """
    if not raw_data:
        return {"points": [], "limits": None, "anomalies": [], "error": "无数据"}

    # 按子组分组（每25条为1子组，或使用已有分组）
    subgroup_size = 25
    subgroups = []
    for i in range(0, len(raw_data), subgroup_size):
        group = raw_data[i:i + subgroup_size]
        if len(group) >= 10:  # 至少需要10条
            subgroups.append(group)

    if len(subgroups) < 2:
        return {"points": [], "limits": None, "anomalies": [], "error": "子组数不足"}

    # 计算每子组不良率和不良品数
    points = []
    for idx, group in enumerate(subgroups):
        n = len(group)
        defect_count = sum(1 for row in group if row.get("result") == "REJ")
        p = defect_count / n if n > 0 else 0
        points.append({
            "subgroup_no": idx + 1,
            "p_value": round(p, 4),
            "np_value": defect_count,
            "sample_size": n,
        })

    # 平均不良率
    total_defects = sum(p["np_value"] for p in points)
    total_samples = sum(p.get("sample_size", subgroup_size) for p in points)
    p_bar = total_defects / total_samples if total_samples > 0 else 0

    # p 图控制限（子组容量不等时用平均n）
    n_avg = total_samples / len(points) if points else subgroup_size
    sigma_p = math.sqrt(p_bar * (1 - p_bar) / n_avg) if n_avg > 0 else 0

    cl_p = round(p_bar, 4)
    ucl_p = round(p_bar + 3 * sigma_p, 4)
    lcl_p = round(max(0, p_bar - 3 * sigma_p), 4)  # 不为负

    # np 图控制限（子组容量固定时使用）
    cl_np = round(p_bar * n_avg, 4)
    sigma_np = math.sqrt(n_avg * p_bar * (1 - p_bar)) if n_avg > 0 else 0
    ucl_np = round(p_bar * n_avg + 3 * sigma_np, 4)
    lcl_np = round(max(0, p_bar * n_avg - 3 * sigma_np), 4)

    limits = {
        "chart_type": "p_np",
        "p": {"cl": cl_p, "ucl": ucl_p, "lcl": lcl_p},
        "np": {"cl": cl_np, "ucl": ucl_np, "lcl": lcl_np},
        "p_bar": p_bar,
        "subgroup_count": len(points),
    }

    # 判异规则检测
    p_values = [p["p_value"] for p in points]
    anomalies = []
    for point in points:
        triggered = nelson_rules(
            {"xbar": point["p_value"]},
            p_values,
            {"xbar": {"cl": cl_p, "ucl": ucl_p, "lcl": lcl_p}},
        )
        if triggered:
            point["is_anomaly"] = True
            point["anomaly_rules"] = json.dumps([t["rule_no"] for t in triggered])
            anomalies.extend(triggered)
        else:
            point["is_anomaly"] = False
            point["anomaly_rules"] = "[]"

    return {"points": points, "limits": limits, "anomalies": anomalies, "error": None}


def calculate_capability(
    data_points: List[float], usl: Optional[float], lsl: Optional[float],
    target: Optional[float] = None,
) -> dict:
    """过程能力分析

    Args:
        data_points: 数据点列表
        usl: 规格上限
        lsl: 规格下限
        target: 目标值

    Returns:
        {"cp", "cpk", "pp", "ppk", "mean", "sigma_within", "sigma_overall", "grade", ...}
    """
    if len(data_points) < 2:
        return {"error": "数据点不足（至少需要2个）"}

    mean = _mean(data_points)
    sigma_overall = _stdev(data_points)  # 总体标准差（长期）

    # 用极差法估算组内标准差（短期）
    # 子组大小n=5的分组
    subgroup_size = 5
    subgroups = []
    for i in range(0, len(data_points), subgroup_size):
        group = data_points[i:i + subgroup_size]
        if len(group) >= 2:
            subgroups.append(group)

    if subgroups:
        r_bar = _mean([max(g) - min(g) for g in subgroups])
        a2, d3, d4 = _get_coefficients(subgroup_size)
        sigma_within = r_bar / d4 if d4 > 0 else sigma_overall
    else:
        sigma_within = sigma_overall

    usl_val = float(usl) if usl is not None else None
    lsl_val = float(lsl) if lsl is not None else None

    # Cp — 过程能力指数
    cp = None
    if usl_val is not None and lsl_val is not None and sigma_within > 0:
        cp = round((usl_val - lsl_val) / (6 * sigma_within), 4)
    elif usl_val is not None and sigma_within > 0:
        cp = round((usl_val - mean) / (3 * sigma_within), 4)
    elif lsl_val is not None and sigma_within > 0:
        cp = round((mean - lsl_val) / (3 * sigma_within), 4)

    # Cpk — 考虑偏移的过程能力指数
    cpk = None
    if sigma_within > 0:
        cpu = (usl_val - mean) / (3 * sigma_within) if usl_val is not None else float('inf')
        cpl = (mean - lsl_val) / (3 * sigma_within) if lsl_val is not None else float('inf')
        cpk_val = min(cpu, cpl)
        cpk = round(cpk_val, 4) if cpk_val != float('inf') else None

    # Pp — 过程性能指数
    pp = None
    if usl_val is not None and lsl_val is not None and sigma_overall > 0:
        pp = round((usl_val - lsl_val) / (6 * sigma_overall), 4)
    elif usl_val is not None and sigma_overall > 0:
        pp = round((usl_val - mean) / (3 * sigma_overall), 4)
    elif lsl_val is not None and sigma_overall > 0:
        pp = round((mean - lsl_val) / (3 * sigma_overall), 4)

    # Ppk — 考虑偏移的过程性能指数
    ppk = None
    if sigma_overall > 0:
        ppu = (usl_val - mean) / (3 * sigma_overall) if usl_val is not None else float('inf')
        ppl = (mean - lsl_val) / (3 * sigma_overall) if lsl_val is not None else float('inf')
        ppk_val = min(ppu, ppl)
        ppk = round(ppk_val, 4) if ppk_val != float('inf') else None

    # 评级
    cp_for_grade = cp if cp is not None else (cpk if cpk is not None else 0)
    if cp_for_grade is not None:
        if cp_for_grade >= 1.67:
            grade = "优"
        elif cp_for_grade >= 1.33:
            grade = "良"
        elif cp_for_grade >= 1.0:
            grade = "一般"
        else:
            grade = "差"
    else:
        grade = "未知"

    return {
        "mean": round(mean, 4),
        "sigma_within": round(sigma_within, 4),
        "sigma_overall": round(sigma_overall, 4),
        "cp": cp,
        "cpk": cpk,
        "pp": pp,
        "ppk": ppk,
        "grade": grade,
        "data_count": len(data_points),
        "usl": usl_val,
        "lsl": lsl_val,
        "target": target,
    }


def nelson_rules(
    point: Dict, all_points: List[float],
    control_limits: Dict,
) -> List[Dict]:
    """Nelson 判异规则检查（7种）

    Args:
        point: 当前数据点 {"xbar": float, "r": float}
        all_points: 所有数据点的值列表
        control_limits: {"xbar": {"cl": float, "ucl": float, "lcl": float}, ...}

    Returns:
        触发的规则列表 [{"rule_no": int, "description": str, "severity": str}]
    """
    triggered = []
    cl = control_limits.get("xbar", {}).get("cl", 0)
    ucl = control_limits.get("xbar", {}).get("ucl", 0)
    lcl = control_limits.get("xbar", {}).get("lcl", 0)
    sigma = (ucl - cl) / 3 if (ucl - cl) > 0 else 1

    value = point.get("xbar", 0)
    idx = len(all_points) - 1  # 当前点在列表中的索引

    # ── 规则1: 1点超出控制限 ──
    if value > ucl or value < lcl:
        triggered.append({
            "rule_no": 1,
            "description": f"第{idx+1}点（值={value:.3f}）超出控制限（UCL={ucl:.3f}, LCL={lcl:.3f}）",
            "severity": "critical",
        })

    # ── 规则2: 连续7点在中心线同侧 ──
    if len(all_points) >= 7:
        recent = all_points[-7:]
        if all(v > cl for v in recent) or all(v < cl for v in recent):
            triggered.append({
                "rule_no": 2,
                "description": f"连续7点（#{(idx-6)+1}~#{idx+1}）在中心线同侧",
                "severity": "high",
            })

    # ── 规则3: 连续7点递增或递减 ──
    if len(all_points) >= 7:
        recent = all_points[-7:]
        if all(recent[i] < recent[i + 1] for i in range(6)) or \
           all(recent[i] > recent[i + 1] for i in range(6)):
            triggered.append({
                "rule_no": 3,
                "description": f"连续7点（#{(idx-6)+1}~#{idx+1}）单调递增或递减",
                "severity": "high",
            })

    # ── 规则4: 连续14点交替上下 ──
    if len(all_points) >= 14:
        recent = all_points[-14:]
        alternating = all(
            (recent[i] > recent[i + 1] and recent[i + 1] < recent[i + 2]) or
            (recent[i] < recent[i + 1] and recent[i + 1] > recent[i + 2])
            for i in range(12)
        )
        if alternating:
            triggered.append({
                "rule_no": 4,
                "description": f"连续14点（#{(idx-13)+1}~#{idx+1}）交替上下",
                "severity": "medium",
            })

    # ── 规则5: 2/3的点在2σ之外（同一侧）──
    if len(all_points) >= 3:
        recent_3 = all_points[-3:]
        side_above = sum(1 for v in recent_3 if v > cl + 2 * sigma)
        side_below = sum(1 for v in recent_3 if v < cl - 2 * sigma)
        cnt = max(side_above, side_below)
        if side_above >= 2 or side_below >= 2:
            triggered.append({
                "rule_no": 5,
                "description": f"最近3点中有{cnt}点在2σ之外（同一侧）",
                "severity": "medium",
            })

    # ── 规则6: 4/5的点在1σ之外（同一侧）──
    if len(all_points) >= 5:
        recent_5 = all_points[-5:]
        side_above = sum(1 for v in recent_5 if v > cl + 1 * sigma)
        side_below = sum(1 for v in recent_5 if v < cl - 1 * sigma)
        if side_above >= 4 or side_below >= 4:
            triggered.append({
                "rule_no": 6,
                "description": f"最近5点中有{side_above or side_below}点在1σ之外（同一侧）",
                "severity": "medium",
            })

    # ── 规则7: 连续15点在1σ之内 ──
    if len(all_points) >= 15:
        recent = all_points[-15:]
        if all(cl - sigma <= v <= cl + sigma for v in recent):
            triggered.append({
                "rule_no": 7,
                "description": f"连续15点（#{(idx-14)+1}~#{idx+1}）在1σ之内（中心线附近）",
                "severity": "low",
            })

    return triggered


def auto_recalc_limits(
    points: List[Dict], chart_type: str,
) -> dict:
    """自动计算控制限（基于已有数据点）

    Args:
        points: 数据点列表 [{"xbar": float, "r": float, ...}]
        chart_type: "xbar_r" | "p" | "np"

    Returns:
        {"cl": float, "ucl": float, "lcl": float, ...}
    """
    if not points:
        return {"cl": 0, "ucl": 0, "lcl": 0, "subgroup_count": 0}

    if chart_type == "xbar_r":
        xbar_values = [p["xbar"] for p in points]
        r_values = [p["r"] for p in points]
        grand_mean = _mean(xbar_values)
        r_bar = _mean(r_values)
        a2, d3, d4 = _get_coefficients(5)

        return {
            "cl": round(grand_mean, 4),
            "ucl": round(grand_mean + a2 * r_bar, 4),
            "lcl": round(grand_mean - a2 * r_bar, 4),
            "subgroup_count": len(points),
        }

    elif chart_type in ("p", "np"):
        p_values = [p["p_value"] for p in points if "p_value" in p]
        if not p_values:
            return {"cl": 0, "ucl": 0, "lcl": 0, "subgroup_count": 0}
        p_bar = _mean(p_values)
        n = len(points)
        sigma_p = math.sqrt(p_bar * (1 - p_bar) / max(n, 1))

        return {
            "cl": round(p_bar, 4),
            "ucl": round(p_bar + 3 * sigma_p, 4),
            "lcl": round(max(0, p_bar - 3 * sigma_p), 4),
            "subgroup_count": len(points),
        }

    return {"cl": 0, "ucl": 0, "lcl": 0, "subgroup_count": 0}
