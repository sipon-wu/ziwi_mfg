"""C-97 `print/batch` 的变异自证：证明 test_print_batch.py 的判据真在判。

## 为什么非做不可

12 条用例首次全绿只说明"没崩"，说明不了它们**看得见错误**。上一轮
`check_menu_permissions.py` 就假绿过一次：解析器返回空串，闸报「0 组，全部通过」。
所以每个关键断言都要配一个"把实现改坏"的对照，看它是否真的变红。

## 恢复策略

★ **不能 `git checkout --`**：本轮的改动还没提交，回退到 HEAD 等于把基线清掉
（B-29 的变异脚本就这么把工作区改没了，只能重做）。统一从 `_BAK` 目录复制回来。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # code/（本文件在 code/scripts/ 下）
BE = ROOT / "backend"
REG = BE / "app/services/print/registry.py"
REN = BE / "app/services/print/renderer.py"
WREPO = BE / "app/repositories/wms_repo.py"
WSVC = BE / "app/services/wms_service.py"
BAK = ROOT / ".workbuddy/_bak_c97"

PY = BE / ".venv/Scripts/python.exe"
TEST = "app/tests/test_print_batch.py"
TEST_DEC = "app/tests/test_batch_decompose.py"

# (名字, 文件, 原串, 替换串, 预期变红的用例关键字, 目标测试文件)
MUTATIONS = [
    (
        "M1 父子方向写反（取 parent_batch_id 当子件）",
        REG,
        "select(Batch)\n            .where(Batch.parent_batch_id == batch.id, Batch.tenant_id == tenant_id)",
        "select(Batch)\n            .where(Batch.id == batch.parent_batch_id, Batch.tenant_id == tenant_id)",
        ["lists_its_children", "six_lines"], TEST,
    ),
    (
        "M2 「子件」从 meta 里整条删掉",
        REG,
        '        ("子件", child_text),\n',
        "",
        ["lists_its_children", "six_lines"], TEST,
    ),
    (
        "M3 locked 当成作废（加进 _VOID_STATUS）",
        REN,
        '_VOID_STATUS = {"voided", "cancelled", "canceled", "rejected", "作废", "已取消"}',
        '_VOID_STATUS = {"voided", "cancelled", "canceled", "rejected", "作废", "已取消", "locked"}',
        ["not_watermarked_as_void"], TEST,
    ),
    (
        "M4 子件段印 material_id 而非物料编码",
        REG,
        "_mat_code(c.material_id),",
        "c.material_id,",
        ["lists_its_children"], TEST,
    ),
    (
        "M5 跨租户不加 tenant 过滤（等于任谁都查得到）",
        REG,
        "select(Batch).where(Batch.id == int(doc_id), Batch.tenant_id == tenant_id)",
        "select(Batch).where(Batch.id == int(doc_id))",
        ["missing_or_foreign"], TEST,
    ),
    # ── 拆解（decompose）────────────────────────────────────────
    (
        "M6 拆解写成 DELETE（把追溯链物理抹掉）",
        WREPO,
        '"UPDATE batches SET parent_batch_id = NULL WHERE parent_batch_id = :id",\n            {"id": parent_batch_id},',
        '"DELETE FROM batches WHERE parent_batch_id = :id",\n            {"id": parent_batch_id},',
        ["releases_children_and_keeps_rows"], TEST_DEC,
    ),
    (
        "M7 去掉「已入库不许拆」这道门禁",
        WSVC,
        "        qty = await self.repo.inventory_qty_of_batch(final_batch_id)\n"
        "        if qty > 0:",
        "        qty = await self.repo.inventory_qty_of_batch(final_batch_id)\n"
        "        if False:",
        ["stocked_code_is_rejected"], TEST_DEC,
    ),
    (
        "M8 没有子件时静默成功（不报错）",
        WSVC,
        # ★ 目标串必须**纯 ASCII 且不带换行转义**：这个脚本是经 heredoc 交给 Python 的，
        #   含中文时 stdin 可能按 GBK 解码 → 求值出来是乱码 → "出现 0 次"被跳过
        #   （M8 第一版就这么逃过一轮，看着 9 个变异全跑，实际只跑了 8 个）。
        #   只取这一行（本文件内唯一），把条件换掉即可。
        "        if not children:",
        "        if False:  # not children",
        ["without_children"], TEST_DEC,
    ),
    (
        "M9 拆解少写 parent_batch_id 条件（清掉全表所有子件关系）",
        WREPO,
        '"UPDATE batches SET parent_batch_id = NULL WHERE parent_batch_id = :id",\n            {"id": parent_batch_id},',
        '"UPDATE batches SET parent_batch_id = NULL WHERE :id IS NOT NULL",\n            {"id": parent_batch_id},',
        # 期望红的这两条各守一个面：
        #   · releases_children：别的成品码的子件被牵连 → 说明条件没限定本码
        #   · detach_children_is_not_idempotent：无条件 UPDATE 每次都影响全表行数，
        #     第二次拆不再返回 0 → 服务层"刚被别人拆过"的判定失效
        ["releases_children_and_keeps_rows", "detach_children_is_not_idempotent"], TEST_DEC,
    ),
]


def _backup():
    BAK.mkdir(parents=True, exist_ok=True)
    for f in (REG, REN, WREPO, WSVC):
        shutil.copy2(f, BAK / f.name)


def _restore():
    for f in (REG, REN, WREPO, WSVC):
        shutil.copy2(BAK / f.name, f)


def _run(test=TEST):
    # ★ 不加 `-x`：加了就停在第一个失败，后面该红的用例根本没机会跑，
    #   于是"预期红的是 A，实际因为 A 先红而没跑到 B"会被误判成判据无效。
    r = subprocess.run([str(PY), "-m", "pytest", test, "-q", "--no-header",
                        "--tb=no", "-p", "no:cacheprovider"],
                       cwd=BE, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    _backup()
    print(f"[bak] 已备份基线到 {BAK}")

    ok_rc, ok_out = _run()
    if ok_rc != 0:
        print("[abort] 基线本来就红，变异对照无意义：\n" + ok_out[-800:])
        return 2
    print(f"[base] 基线全绿：{ok_out.strip().splitlines()[-1]}")

    bad = 0
    for name, path, old, new, expect, test in MUTATIONS:
        src = path.read_text(encoding="utf-8")
        n = src.count(old)
        if n != 1:
            print(f"[fatal] {name}：目标串出现 {n} 次（必须恰好 1 次），跳过")
            bad += 1
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        rc, out = _run(test)
        _restore()

        if rc == 0:
            print(f"[FAIL] {name} —— 改坏了还是全绿，这条判据是假的")
            bad += 1
            continue
        hit = [k for k in expect if k in out]
        tail = [ln for ln in out.strip().splitlines() if "FAILED" in ln or "failed" in ln]
        # 判据：expect 里列的用例**全都要红**。只要有一条没红，说明那条用例
        # 根本没在守这个变异点（它是搭便车绿的）。
        if len(hit) == len(expect):
            print(f"[ok] {name} → 变红，命中 {','.join(hit)}")
        else:
            print(f"[FAIL] {name} → 只红了 {hit or '无'}，"
                  f"预期 {expect} 全部要红")
            bad += 1
        for ln in tail[:3]:
            print(f"       {ln.strip()}")

    _restore()
    rc, out = _run()
    print(f"\n[restore] 恢复后：{'全绿' if rc == 0 else '仍然红（恢复失败！）'}"
          f" {out.strip().splitlines()[-1] if out.strip() else ''}")
    if rc != 0:
        bad += 1

    print(f"\n结论：{len(MUTATIONS)} 个变异，{bad} 个不合格")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
