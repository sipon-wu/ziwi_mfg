"""静态闸：固定列 INSERT 不得漏写「模型上有 Python 侧 default」的列。

为什么必须有这道闸
------------------
这个形态**已复发八次**：

    C-34 equipment.status              C-48 energy_alert.status
    C-50 work_orders.assignee_id       C-56 inventory_counts.counted_items/diff_items
    C-56 明细列                        C-57 materials.pick_strategy
    C-63 roles.is_system               C-64 本轮 71 处（其中 11 处已用 NULL 行数证伪为实锤）

它不是"字段显示为空"的观感问题，而是**行为静默改变**：
`pick_strategy` 落 NULL → `dict.get(k, "fifo")` 不生效 → FIFO 静默反转成 LIFO；
`escalation_level` 落 NULL → `>= 2` 恒假 → 该升级的安灯呼叫永远升不上去。
**靠 review 拦不住，必须上闸。**

为什么用"基线冻结"而不是让 CI 直接红
--------------------------------------
存量里有一批历史违规。一次性让闸变红，结果只会是"没人看 / 直接关掉" ——
C-60 那次路由闸第一版报了 20 条误报，教训就是**闸一旦成为噪音就没人信**。
这里采用 ratchet（棘轮）：

- 存量冻结在 `.workbuddy/baseline/insert_missing_defaults.json`
- **新增违规 → 测试失败**（增量禁止）
- 存量被修好 → 测试会提示"已从基线移除，请更新基线"（鼓励只减不增）

如何更新基线
------------
修完一批后执行（会重写基线，务必确认 diff 是"变少"而不是"变多"）：:

    cd backend && ./.venv/Scripts/python.exe ../scripts/check_insert_defaults.py --write-baseline
"""

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
# 基线在仓库内（.workbuddy 被 gitignore，放那里会导致 clone 后闸直接失败）
BASELINE_PATH = os.path.join(REPO_ROOT, "backend", "app", "tests", "baseline",
                             "insert_missing_defaults.json")


def _load_scanner():
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_check_insert_defaults", os.path.join(SCRIPTS_DIR, "check_insert_defaults.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _key(x):
    return (x["file"], x["table"], x["column"])


def test_no_new_insert_missing_defaults():
    """新增代码不得再漏写带默认值的列。"""
    mod = _load_scanner()
    findings = mod.scan()

    frozen = []
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, encoding="utf-8") as f:
            frozen = json.load(f).get("frozen", [])
    frozen_keys = {_key(x) for x in frozen}
    current_keys = {_key(x) for x in findings}

    new = [x for x in findings if _key(x) not in frozen_keys]
    if new:
        pretty = "\n".join(
            f"  - {x['file']}:{x['line']}  {x['table']}.{x['column']} "
            f"(模型 default={x['default']})" for x in new)
        pytest.fail(
            f"发现 {len(new)} 处**新增**的「INSERT 漏写带默认值的列」。\n"
            f"裸 SQL 拿不到 ORM 侧的 Python default，不写就是 NULL（该形态已复发八次）。\n"
            f"请在对应 repo 的 INSERT 里补上该列（写入口 setdefault 兜住）。\n"
            f"{pretty}\n\n"
            f"若确属历史遗留且本轮不修，可把它加入基线：\n"
            f"  cd backend && ./.venv/Scripts/python.exe "
            f"../scripts/check_insert_defaults.py --write-baseline")


def test_baseline_only_shrinks():
    """基线里已修好的项应当被清理，避免基线变成"永远不清的账"。"""
    mod = _load_scanner()
    if not os.path.exists(BASELINE_PATH):
        pytest.skip("基线文件不存在（首次运行请先 --write-baseline）")

    with open(BASELINE_PATH, encoding="utf-8") as f:
        frozen = json.load(f).get("frozen", [])
    current_keys = {_key(x) for x in mod.scan()}
    stale = [k for k in {_key(x) for x in frozen} if k not in current_keys]

    assert not stale, (
        "以下基线项已被修好，请更新基线（只应减少、不应增加）：\n"
        + "\n".join(f"  - {k[0]} {k[1]}.{k[2]}" for k in sorted(stale))
        + "\n\n  cd backend && ./.venv/Scripts/python.exe "
          "../scripts/check_insert_defaults.py --write-baseline")
