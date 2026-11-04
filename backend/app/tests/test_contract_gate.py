"""契约闸必须同时挂在 pytest 上，不能只挂在 ``e2e/run_all.py`` 上。

为什么要有这一条：``run_all.py`` 要起真服务、跑 48 个探针、连 staging 时才用，
日常改代码基本只跑 pytest。一个"只在合并前跑一次"的闸，拦不住日常提交 ——
而本轮 9 个契约类缺陷全是日常提交攒下来的。

被测的闸是 ``scripts/check_contracts.py``：纯静态（不连库、不起服务），拿
**模型**当基准去对账手写 SQL 的列名、拿**仓储类**当基准去对账 service 的方法名。
存量已录 ``scripts/contracts_baseline.json``，只拦新增 —— 所以这个用例红了，
意味着这次改动**新引入**了一处两侧对不上的名字。
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND.parent / "scripts" / "check_contracts.py"


def test_contract_gate_has_no_new_violations():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(BACKEND), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, (
        "契约闸红了：新增了「代码里写的名字在另一侧不存在」的问题。\n"
        "修代码后重跑；确认要接受存量，跑 "
        "`python ../scripts/check_contracts.py --update-baseline`。\n\n" + out
    )
