"""探针回收规则（``scripts/probe_artifacts.py::ROOT_PATTERNS``）的闸。

## 为什么需要

2026-11-07 在 staging 清残留时发现：`work_orders` 那段注释写着

    # 整类前缀就是探针的：`E2E-SP-*` / `E2E-MG*` / `WO-E2E-*`
    r"^E2E[-_]",

但正则只有 `^E2E[-_]` —— `WO-E2E-003553a9efd` 压根不匹配，**20 条一直躺在库里
没人回收**。而工具自己会打印「根表已无匹配行」「业务数据一行不少」，看着完全干净。

这类缺陷的形状是：**注释承诺了一条规则，代码没有实现它**。读代码的人看到注释
以为覆盖了，跑工具的人看到校验全过以为清干净了，两边都不会发现少了一族。

所以本闸做三件事（缺一件就会漏）：

1. **把注释里点名的每个命名样例变成断言** —— 注释说认识它，就必须真能匹配；
2. **负向用例** —— 保养任务 `MT-1-20261105` 是 8 位日期，被默认规则
   `[-_][0-9]{10}$` 误伤过一次（实测误报 3 行），必须继续不匹配；
3. **结构化自检** —— `ROOT_PATTERNS` 的键必须真的是一张根表，否则那条规则
   静默变成死代码（表改名后最容易出这种，且没有任何报错）。
"""
import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND.parent / "scripts" / "probe_artifacts.py"


def _load():
    spec = importlib.util.spec_from_file_location("probe_artifacts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pa = _load()


def _matches(table: str, name: str) -> bool:
    """按工具的真实判定口径：专用规则表存在则用专用规则，否则用默认规则。"""
    patterns = pa.ROOT_PATTERNS.get(table)
    if patterns:
        return any(re.search(p, name) for p in patterns)
    return bool(re.search(pa.DEFAULT_PATTERN, name))


#: **注释里点名过的**每一个命名样例都要真能匹配。
#: 新增一条注释举例，就往这里加一行 —— 否则注释又会跑在实现前面。
DOCUMENTED = {
    "work_orders": [
        "E2E-MG1-1105115414-M1",      # 拆分/合并子单
        "WO-DUP-1105115428-B",        # 同上，WO- 前缀版
        "E2E-SP-0001",               # 整类前缀 E2E-SP-*
        "E2E-MG1-0001",              # 整类前缀 E2E-MG*
        "WO-E2E-003553a9efd",        # 整类前缀 WO-E2E-*（2026-11-07 才真的实现）
        "WO-E2E-003553a9efd-B",      # 它的拆分子单
        "WO-W-115609",               # 仓储写实
        "RW-NC-WR111",               # SPC/NCR 闭环
        "WO_20261105121007_c45196_1",  # closed_loop_test
        "WO-20261105-115506",        # 自动编号
    ],
    "products": ["E2E-FG-001", "GE31234567890"],
    "materials": [
        "E2E-MAT", "E2E-TRACE-RM", "E2E_LOOP_20261107003420_f51afb_RAW",
        "P-E2E", "MAT-TC4-123456",
    ],
    "process_routes": ["RTE-P-GE-12-V2", "RT-TS-123456"],
    "users": ["tmpu1105115407", "rouser1107003308", "inspector_1107003246"],
}


class TestDocumentedNamingsAreActuallyMatched:
    def test_every_documented_naming_matches(self):
        missing = [
            f"{table}: {name}"
            for table, names in DOCUMENTED.items()
            for name in names
            if not _matches(table, name)
        ]
        assert not missing, (
            "注释里点名的探针命名，规则却匹配不上 —— 注释跑在实现前面了：\n  "
            + "\n  ".join(missing)
        )

    def test_work_orders_specifically_covers_wo_e2e(self):
        """单独钉一条：这一族就是本次漏掉的，别再漏第二次。"""
        assert _matches("work_orders", "WO-E2E-003553a9efd")
        assert _matches("work_orders", "WO-E2E-003553a9efd-B")


class TestNoFalsePositives:
    """反向用例。没有负向用例的闸 = 没有闸：`.*` 能让上面全绿。"""

    def test_maintenance_task_with_8_digit_date_is_not_probe(self):
        # 保养任务 `MT-1-20261105`：默认规则若放宽成 {8,} 就会误伤（实测误报 3 行）
        assert not _matches("work_orders", "MT-1-20261105")

    def test_typo_variants_do_not_match(self):
        assert not _matches("work_orders", "WO-E2X-1105115414")
        assert not _matches("work_orders", "XWO-E2E-0001")
        assert not _matches("work_orders", "WO-E2E")          # 前缀不完整
        assert not _matches("products", "E2E")                # 无分隔符

    def test_real_accounts_are_not_probe(self):
        assert not _matches("users", "mfg_admin")
        assert not _matches("users", "ah_admin")


class TestStructure:
    def test_pattern_keys_are_real_root_tables(self):
        """规则键写错表名 = 那条规则静默变成死代码（表改名后的典型残留）。"""
        roots = {r[0] for r in pa.ROOTS}
        orphans = set(pa.ROOT_PATTERNS) - roots
        assert not orphans, f"ROOT_PATTERNS 里有不存在的根表：{sorted(orphans)}"

    def test_default_pattern_still_locked_to_10_digits(self):
        """`{10,}` 这条硬约束不能放宽 —— 放宽就会把 8 位日期的种子编码算成垃圾。"""
        assert pa.DEFAULT_PATTERN == r"[-_][0-9]{10}$"
