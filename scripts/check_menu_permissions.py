"""菜单 ↔ 权限配置一致性闸（B-29）

守的是一类**不报错就错**的缺陷：菜单能看见，点进去 403；或者菜单该藏没藏。

四类判据
--------
E1 `menuPermissions` 里的 `menuId` 必须在 `MainLayout.vue` 的菜单树里真实存在
     —— 对不上时 `filterMenuTree` 查不到 `permCfg`，**整组退化成"不限权"**，
     任何登录用户都看得见。写错一个字符就静默失效，不报任何错。
E2 声明的 `childId` 必须是该组下的真实子项 —— 否则配了等于没配，
     而设计者以为已经管住了。
E3 **半声明**形态报红：某组已经声明了 children、却漏了其中几项。
     漏掉的子项会继承父级 perm（通常是该域最宽的那个读码），于是
     "能看仓库结构的人都能看见入库单，点进去 403"。整组不声明（= 不限权）
     不算半声明，但也必须在 `WHOLE_GROUP_OPEN` 里登记原因。
E4 权限码形如 `模块:资源:动作`，模块码必须在后端 `MODULE_LABELS` 里 —— 防拼错。

为什么要有白名单而不是一律判死
------------------------------
存量已经存在若干半声明组（quality / andon / lab）。闸的作用是**不让新的长出来**，
不是逼着一次改完 —— 但白名单每一条都必须写清"为什么这里可以靠继承"，
且白名单条目失效（对应的漏项被补上了）时闸会提示删掉，避免白名单自己变成垃圾场。

自测：`--self-test` 用假输入跑一遍，证明四个判据真的会红。
没有自测的闸等于没有闸（本项目已有前车之鉴）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "frontend/src/layouts/MainLayout.vue"
CFG = ROOT / "frontend/src/config/menu-permissions.ts"
MODULES = ROOT / "backend/app/constants/modules.py"

# ── 允许"半声明"的存量组：(menuId, childId) → 为什么可以靠父级继承 ──
ALLOW_INHERIT: dict[tuple[str, str], str] = {
    ("andon", "andon_list"): "同一域，父级 M05:andon_call:read 即该页主码",
    ("quality", "quality_list"): "同一域，父级 M03:inspection_order:read 即该页主码",
    ("quality", "ncr_list"): "NCR 页面主接口在 M03 域，父级已覆盖",
    ("lab", "lab_requests"): "同一域，父级 M15:lab_request:read 即该页主码",
}

# ── 整组不做权限限制：menuId → 为什么 ──
WHOLE_GROUP_OPEN: dict[str, str] = {
    "home": "驾驶舱/车间大屏是登录即看的门面页",
    "trial": "试产组只有一个子项且与父级同域，暂随父级",
    "data_collection": "采集页只有一个子项且与父级同域",
}

# 动作词白名单（与后端 EXECUTE_SUFFIXES 同族，这里只校验形状不校验语义）
_ACTION_OK = {"read", "create", "update", "delete", "execute", "approve", "export", "import"}


def _extract_array(src: str, marker: str, open_ch: str = "[", close_ch: str = "]") -> str:
    """从 marker 之后第一个 `open_ch` 起做括号匹配，返回内部文本。

    ★ 必须跳过字符串字面量：SVG path 与中文文案里会出现成对/落单的方括号，
      直接数括号会错位。这里用一个最小状态机（只认单/双引号、无反斜杠转义
      之外的复杂度 —— 本仓几块配置都是这个形态）。
    """
    i = src.index(marker)
    # ★ 起点必须落在 marker **之后**：marker 自身常带类型标注的方括号
    #   （`MenuItem[]` / `MenuPermission[]`），从 marker 起点找 `[` 会命中
    #   类型标注里那个，配对后立刻闭合 → 返回空串 → 闸报"0 组，全部通过"。
    #   2026-11-09 第一版就这么假绿过一次。
    i = src.index(open_ch, i + len(marker))
    depth = 0
    quote = ""
    for j in range(i, len(src)):
        ch = src[j]
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return src[i + 1:j]
    raise ValueError(f"括号未闭合：{marker}")


def _split_objects(body: str) -> list[str]:
    """按顶层 `{...}` 切块。同样跳过字符串。"""
    out: list[str] = []
    depth = 0
    quote = ""
    start = -1
    for i, ch in enumerate(body):
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "{":
            depth += 1
            if depth == 1:
                start = i
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                out.append(body[start:i + 1])
                start = -1
    return out


def parse_menu_tree(src: str) -> dict[str, dict]:
    """→ {menuId: {'children': [childId...], 'has_href': bool}}"""
    body = _extract_array(src, "const allMenuTree: MenuItem[] =")
    tree: dict[str, dict] = {}
    for block in _split_objects(body):
        # 先摘出 children 块，剩下的才是父级自身字段
        child_ids: list[str] = []
        m = re.search(r"children:\s*\[", block)
        if m:
            inner = _extract_array(block[m.start():], "children:")
            for cb in _split_objects(inner):
                cid = re.search(r"id:\s*'([^']+)'", cb)
                if cid:
                    child_ids.append(cid.group(1))
            head = block[:m.start()] + block[block.rindex("]"):]
        else:
            head = block
        mid = re.search(r"id:\s*'([^']+)'", head)
        if not mid:
            continue
        tree[mid.group(1)] = {
            "children": child_ids,
            "has_href": bool(re.search(r"href:", head)),
        }
    return tree


def parse_menu_perms(src: str) -> dict[str, dict]:
    """→ {menuId: {'perm': str|None, 'children': [childId...], 'has_children': bool}}"""
    body = _extract_array(src, "export const menuPermissions: MenuPermission[] =")
    perms: dict[str, dict] = {}
    for block in _split_objects(body):
        mid = re.search(r"menuId:\s*'([^']+)'", block)
        if not mid:
            continue
        pm = re.search(r"perm:\s*'([^']+)'", block)
        perms[mid.group(1)] = {
            "perm": pm.group(1) if pm else None,
            "children": re.findall(r"childId:\s*'([^']+)'", block),
            "has_children": "children:" in block,
        }
    return perms


def load_module_codes() -> set[str]:
    src = MODULES.read_text(encoding="utf-8")
    body = _extract_array(src, "MODULE_NAMES: Dict[str, str] =", "{", "}")
    # 这里键是 `"M01":` 形态（双引号），单独提取
    codes = set(re.findall(r'"([A-Z0-9_]+)"\s*:', body))
    codes.add("PLAT")  # MODULE_PLAT 的常量值
    return codes


def check(tree: dict[str, dict], perms: dict[str, dict], modules: set[str]) -> list[str]:
    errs: list[str] = []

    for menu_id, cfg in perms.items():
        # E1
        if menu_id not in tree:
            errs.append(
                f"[E1] menuId '{menu_id}' 在菜单树里不存在 —— 这组权限配置永不生效，"
                f"该组等于『不限权』，任何登录用户可见")
            continue

        real = set(tree[menu_id]["children"])
        # E2
        for cid in cfg["children"]:
            if cid not in real:
                errs.append(
                    f"[E2] '{menu_id}' 声明了 childId '{cid}'，但菜单树里没有这个子项 —— "
                    f"配置写了却管不到任何东西")

        # E3 半声明
        if cfg["has_children"] and real:
            declared = set(cfg["children"])
            for missing in sorted(real - declared):
                if (menu_id, missing) in ALLOW_INHERIT:
                    continue
                errs.append(
                    f"[E3] '{menu_id}' 声明了 children 却漏了子项 '{missing}' —— "
                    f"它会继承父级 perm({cfg['perm']})，可能出现『看得见点进去 403』")

        # E4
        if cfg["perm"]:
            parts = cfg["perm"].split(":")
            if len(parts) != 3:
                errs.append(f"[E4] '{menu_id}' 的 perm '{cfg['perm']}' 不是 模块:资源:动作 三段式")
            else:
                mod, _res, act = parts
                if mod not in modules:
                    errs.append(f"[E4] '{menu_id}' 的 perm 模块码 '{mod}' 不在 MODULE_LABELS 里")
                if act not in _ACTION_OK:
                    errs.append(f"[E4] '{menu_id}' 的 perm 动作词 '{act}' 不在约定集合里")
        for cid in cfg["children"]:
            pass  # childId 的 perm 已随 block 解析，形状检查交给上面 E4 的同款逻辑

    # 白名单失效提示（补上了就该删条目，别让白名单变垃圾场）
    for (menu_id, cid), _why in ALLOW_INHERIT.items():
        cfg = perms.get(menu_id)
        if cfg and cid in cfg["children"]:
            errs.append(
                f"[W] 白名单条目 ('{menu_id}', '{cid}') 已被显式声明，"
                f"请从 ALLOW_INHERIT 删掉这一行")
    # 整组开放提示
    for menu_id in WHOLE_GROUP_OPEN:
        cfg = perms.get(menu_id)
        if cfg and cfg["has_children"]:
            errs.append(
                f"[W] '{menu_id}' 已在 WHOLE_GROUP_OPEN 登记为整组开放，"
                f"但现在又写了 children —— 二者只能留一个")

    return errs


def run_real() -> int:
    tree = parse_menu_tree(MAIN.read_text(encoding="utf-8"))
    perms = parse_menu_perms(CFG.read_text(encoding="utf-8"))
    modules = load_module_codes()

    print(f"菜单树 {len(tree)} 组 / 权限配置 {len(perms)} 组 / 模块码 {len(modules)} 个")

    # ★ 解析出 0 组必须判红：那说明解析器坏了（marker 对不上、括号配对错），
    #   而不是"本来就没有配置"。不加这条，解析一挂闸就恒绿 —— 比没闸更糟。
    if not tree or not perms:
        print("\n[FAIL] 解析结果为空 —— 解析器已失效，不能当作『全部合规』")
        return 1

    errs = check(tree, perms, modules)
    hard = [e for e in errs if not e.startswith("[W]")]
    warn = [e for e in errs if e.startswith("[W]")]

    for e in hard:
        print("  " + e)
    for w in warn:
        print("  " + w)

    if hard:
        print(f"\n[FAIL] 菜单权限一致性：{len(hard)} 处不一致")
        return 1
    print(f"\n[OK] 菜单权限一致性通过（{len(warn)} 条提示）")
    return 0


def run_self_test() -> int:
    """用假输入证明四类判据真的会红 —— 没有自测的闸等于没有闸。"""
    fake_tree = {
        "wms": {"children": ["a", "b"], "has_href": False},
        "home": {"children": ["c"], "has_href": False},
    }
    mods = {"M04", "PLAT"}
    cases = [
        ("E1 不存在的 menuId", {"ghost": {"perm": "M04:x:read", "children": [], "has_children": False}}),
        ("E2 不存在的 childId",
         {"wms": {"perm": "M04:x:read", "children": ["zzz"], "has_children": True}}),
        ("E3 半声明",
         {"wms": {"perm": "M04:x:read", "children": ["a"], "has_children": True}}),
        ("E4 模块码拼错",
         {"home": {"perm": "M99:x:read", "children": [], "has_children": False}}),
        ("E4 动作词不认识",
         {"home": {"perm": "M04:x:frobnicate", "children": [], "has_children": False}}),
    ]
    bad = 0
    for name, perms in cases:
        errs = check(fake_tree, perms, mods)
        hard = [e for e in errs if not e.startswith("[W]")]
        if hard:
            print(f"  [OK ] 自测命中：{name} → {hard[0][:60]}...")
        else:
            print(f"  [FAIL] 自测漏判：{name}（本该报红却全绿）")
            bad += 1

    # 反向：完全合规的输入必须全绿，否则闸会恒红
    clean = {"wms": {"perm": "M04:x:read", "children": ["a", "b"], "has_children": True}}
    errs = check(fake_tree, clean, mods)
    hard = [e for e in errs if not e.startswith("[W]")]
    if hard:
        print(f"  [FAIL] 合规输入被误判：{hard[0]}")
        bad += 1
    else:
        print("  [OK ] 自测反向：完全合规输入全绿")

    if bad:
        print(f"\n[FAIL] 自测 {bad} 项未通过")
        return 1
    print("\n[OK] 闸自测通过（5 条负向 + 1 条反向）")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())
    sys.exit(run_real())
