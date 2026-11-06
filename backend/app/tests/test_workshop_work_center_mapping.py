"""车间建模：工位编码清单闸（2026-11-06）。

背景
----
《推进器生产工艺流程及数据采集表》口径：工艺卡工序序号 1~19 在**一般车间**、
20~30 在**无尘车间**（30「CW190 入库终检包装」经确认并入无尘）。
落到系统 = 33 个 ``WC-AH-*`` 工位分别归属两个 ``workshop`` 组织节点，
执行器是 ``migrations/20261106f_workshop_org_backfill.py``。

为什么要这条闸
--------------
归属靠**手写编码清单**（``GEN_CODES`` / ``CLN_CODES``）。这类清单最容易出的错
是"看起来对"：

- 少抄一个工位 → 迁移打印"回填 32 行"，没人会去数是不是该 33
- 同一个工位抄进两个车间 → ``UPDATE`` 执行两次，最后落到后一个，静默
- 编码打错一个字 → ``IN (...)`` 匹配不到，静默 0 行

迁移脚本内部已有 ``_check_code_lists()`` 做数量/重复/交集自检，但它只在
"有人手工跑迁移"时才执行。这条测试把同一套约束提前到 CI/pytest 阶段，
并且**自带负向用例** —— 没有负向用例的闸等于没有闸（只会打印 OK 的代码）。
"""
import importlib.util
import pathlib

import pytest

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations" / "20261106f_workshop_org_backfill.py"
)


def _load_migration():
    if not MIGRATION.exists():
        pytest.skip(f"迁移脚本不存在：{MIGRATION}")
    spec = importlib.util.spec_from_file_location("_ws_org_backfill", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_migration()


# ── 清单结构 ────────────────────────────────────────────────────────────

def test_workshop_nodes_defined():
    """两个车间节点：编码、名称、类型都要齐。"""
    assert [w[0] for w in M.WORKSHOPS] == ["AH-WS-GEN", "AH-WS-CLN"]
    names = {w[0]: w[1] for w in M.WORKSHOPS}
    assert names["AH-WS-GEN"] == "一般车间"
    assert names["AH-WS-CLN"] == "无尘车间"
    # 每项都要有备注，避免以后有人加车间只填编码不写口径
    assert all(len(w) == 4 and (w[3] or "").strip() for w in M.WORKSHOPS)


def test_counts_match_33_work_centers():
    """19 + 14 = 33，与该租户 ``WC-AH-%`` 工位数一致。"""
    assert len(M.GEN_CODES) == 19
    assert len(M.CLN_CODES) == 14
    assert len(M.GEN_CODES) + len(M.CLN_CODES) == 33


def test_no_duplicate_and_no_overlap():
    """同一工位不能重复、更不能被两个车间抢。"""
    assert len(set(M.GEN_CODES)) == len(M.GEN_CODES)
    assert len(set(M.CLN_CODES)) == len(M.CLN_CODES)
    assert not (set(M.GEN_CODES) & set(M.CLN_CODES))


def test_all_codes_are_ah_work_centers():
    """编码前缀统一 —— 迁移按 ``WC-AH-`` 命名空间回填，前缀错了就匹配不到。"""
    for code in M.GEN_CODES + M.CLN_CODES:
        assert code.startswith("WC-AH-"), code
        assert code == code.strip(), code


def test_line_split_matches_process_card():
    """按工艺卡分工：定子 7 / 转子 6 / 总装前段 6 在一般，PCB 段起在无尘。"""
    gen_prefix = {c.split("-")[2][:2] for c in M.GEN_CODES}
    assert gen_prefix == {"CW", "RT", "MA"}, gen_prefix
    # 无尘车间不应出现 RT / CW030 这类前半段工序
    cln = set(M.CLN_CODES)
    assert not [c for c in cln if c.startswith("WC-AH-RT")]


def test_aged_and_inbound_in_clean_room():
    """老化（EL030）与入库（CW190）都归无尘 —— 2026-11-06 与客户确认的口径。

    这两条是最容易被"想当然"改掉的两条：老化常被当成"线外"（所以工艺卡写
    「线外-老化测试」），入库常被当成"普通区"。改它们会直接改变车间边界。
    """
    assert "WC-AH-EL030" in M.CLN_CODES
    assert "WC-AH-CW190" in M.CLN_CODES


# ── 负向用例：闸必须真的能抓到毛病 ─────────────────────────────────────

def test_gate_catches_wrong_count():
    """少抄一个工位 → 必须在 ``_check_code_lists`` 就炸掉。"""
    broken = M.CLN_CODES[:-1]
    original = M.CLN_CODES
    try:
        M.CLN_CODES = broken
        with pytest.raises(SystemExit) as exc:
            M._check_code_lists()
        assert "14" in str(exc.value)
    finally:
        M.CLN_CODES = original


def test_gate_catches_overlap():
    """同一工位落进两个车间 → 必须炸掉（否则后一次 UPDATE 静默覆盖）。

    ★ 用**替换**而不是追加：追加会让数量变成 15，先被数量闸拦下，
      「两车间抢同一工位」这条分支就永远没被执行到 —— 测了个寂寞。
    """
    original = M.CLN_CODES
    try:
        M.CLN_CODES = original[:-1] + [M.GEN_CODES[0]]
        with pytest.raises(SystemExit) as exc:
            M._check_code_lists()
        assert "抢" in str(exc.value), str(exc.value)
    finally:
        M.CLN_CODES = original


def test_migration_skips_without_tenant():
    """不带 --tenant 时必须安静跳过，返回 0。

    ``deploy.sh`` 第 5 步会无参数全量 ``python /app/migrations/*.py`` 跑一遍。
    本迁移若在缺参数时 argparse error，每次部署都会往日志里刷红色 usage ——
    而"迁移日志没人看"正是此前 5 个迁移从未在 staging 执行过的成因。
    """
    import sys
    argv_backup = sys.argv
    try:
        sys.argv = ["20261106f_workshop_org_backfill.py"]
        assert M.main() == 0
    finally:
        sys.argv = argv_backup
