// role_crud_e2e.js — 角色增删改界面端到端验证（真实浏览器 + 真实后端）
//
// 前置：后端 :8000 + 前端 :5173（产物为最新构建）已启动。
//
// 背景（docs/BACKLOG.md #B-1）：
//   「系统管理 → 角色权限」此前只能给**已有**角色勾权限 —— 不能新建角色、
//   不能改名、不能删角色。后端 `POST/PUT/DELETE /roles` 与
//   `POST /roles/{id}/users` 全都做好了，纯粹是界面没接。
//   客户上线时角色清单是死的（9 个种子角色），任何组织差异都得改代码。
//
// 断言：
//   E1  admin 能进角色页，左侧有「+ 新建」
//   E2  新建角色 → 出现在列表里，且被自动选中
//   E3  新角色默认无权限、数据范围按表单落库
//   E4  编码重复 → 页面内报后端人话（不是"创建失败"）
//   E5  编辑角色名 → 左侧列表与右侧标题同步更新
//   E6  内置角色的「删除」按钮禁用
//   E7  删除非内置角色 → 列表里消失
//   E8  给角色加成员 → 成员区出现该用户，左侧「N 人」跟着变
//   E9  department_head（无 PLAT:role:create）看不到「+ 新建」
//   E10 全程 0 JS 错误
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'role_crud');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const TS = Date.now().toString().slice(-6);
const ROLE_CODE = `e2e_role_${TS}`;
const ROLE_NAME = `E2E仓库主管${TS}`;

const results = [];
function rec(id, name, ok, detail) {
  const status = (ok === true || ok === 'PASS') ? 'PASS' : 'FAIL';
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (/Failed to load resource/i.test(t)) return;
    consoleErrors.push(t);
  });
  page.on('pageerror', e => consoleErrors.push('[pageerror] ' + e.message));

  async function shot(id) {
    try { await page.screenshot({ path: path.join(SHOT, `${id}.png`), fullPage: false }); } catch {}
  }

  async function loginAs(username, password) {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const res = await page.evaluate(async ({ username, password }) => {
      const r = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, tenant_id: 'AH-THR' }),
      });
      const data = await r.json().catch(() => null);
      if (!r.ok) return { ok: false, status: r.status };
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token || '');
      localStorage.setItem('tenant_id', 'AH-THR');
      const raw = await fetch('/api/v1/auth/me', {
        headers: { Authorization: 'Bearer ' + data.access_token, 'X-Tenant-Id': 'AH-THR' },
      }).then(x => x.json());
      const me = raw && raw.data ? raw.data : raw;
      localStorage.setItem('user_info', JSON.stringify(me));
      return { ok: true, perms: (me.permissions || []).length, username: me.username };
    }, { username, password });
    // 必须硬刷新：只改 hash 不重跑 main.ts 的 auth.init()
    await page.goto(`${BASE}/#/cockpit`, { waitUntil: 'networkidle', timeout: 30000 });
    await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
    await sleep(700);
    return res;
  }

  async function openRoles() {
    await page.goto(`${BASE}/#/system/roles`, { waitUntil: 'networkidle', timeout: 30000 });
    await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1200);
  }

  const roleNames = () => page.locator('.rp-role__name');
  const roleCodes = () => page.locator('.rp-role__code');
  async function listHas(code) {
    const n = await roleCodes().count();
    for (let i = 0; i < n; i++) {
      if ((await roleCodes().nth(i).innerText()).trim() === code) return true;
    }
    return false;
  }
  /** 按编码点选左侧角色（列表按 created_at DESC，第一条不一定是目标） */
  async function selectByCode(code) {
    const n = await roleCodes().count();
    for (let i = 0; i < n; i++) {
      if ((await roleCodes().nth(i).innerText()).trim() === code) {
        await page.locator('.rp-role').nth(i).click();
        await sleep(900);
        return true;
      }
    }
    return false;
  }

  /* ══════════ E1 admin 进入 + 新建按钮 ══════════ */
  const admin = await loginAs('mfg_admin', 'admin123');
  rec('E1', 'admin 登录', admin.ok, `perms=${admin.perms}`);
  const adminHasCreate = (admin.perms || 0) > 0;
  await openRoles();
  const createBtnVisible = await page.locator('.rp-roles__hd button:visible').count();
  rec('E1', '左侧有「+ 新建」按钮', createBtnVisible > 0, `count=${createBtnVisible}`);
  await shot('E1_roles');

  /* ══════════ E2 新建角色 ══════════ */
  await page.locator('.rp-roles__hd button').first().click();
  await sleep(500);
  const popup = page.locator('.rp-popup:visible').first();
  rec('E2', '新建弹窗打开', (await popup.count()) > 0, '');
  await popup.locator('input').nth(0).fill(ROLE_NAME);
  await popup.locator('input').nth(1).fill(ROLE_CODE);
  await popup.locator('input').nth(2).fill('E2E 建的角色，用完即删');
  await shot('E2_create_form');
  await popup.locator('.rp-popup__ft button').last().click();
  await sleep(1500);

  const hasNew = await listHas(ROLE_CODE);
  rec('E2', '新角色出现在左侧列表', hasNew, `code=${ROLE_CODE}`);
  const activeName = await page.locator('.rp-role.is-active .rp-role__code').innerText().catch(() => '');
  rec('E2', '新建后自动选中该角色', activeName.trim() === ROLE_CODE, `active=${activeName.trim()}`);
  await shot('E2_created');

  /* ══════════ E3 默认无权限 + 数据范围落库 ══════════ */
  const statsText = await page.locator('.rp-head__stats').innerText().catch(() => '');
  rec('E3', '新角色默认 0 项权限', /0/.test(statsText), statsText.replace(/\s+/g, ' '));
  // 数据范围是角色属性，右侧「数据范围」区按 scope 高亮当前选项
  const scopeChip = await page
    .locator('.rp-scope__opt.is-active .rp-scope__label')
    .first()
    .innerText()
    .catch(() => '');
  rec('E3', '数据范围按表单落库（「本部门」）', /本部门/.test(scopeChip), `scope=${scopeChip.replace(/\s+/g, ' ').slice(0, 40)}`);

  /* ══════════ E4 编码重复 → 页面内人话 ══════════ */
  await page.locator('.rp-roles__hd button').first().click();
  await sleep(400);
  const popup2 = page.locator('.rp-popup:visible').first();
  await popup2.locator('input').nth(0).fill(ROLE_NAME + '重复');
  await popup2.locator('input').nth(1).fill(ROLE_CODE);
  await popup2.locator('.rp-popup__ft button').last().click();
  // 等后端返回 + 错误行渲染（不要固定 sleep，慢机器会抢跑）
  await page.locator('.rp-popup:visible .rp-popup__err').first()
    .waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});
  const errText = await page.locator('.rp-popup:visible .rp-popup__err').first().innerText().catch(() => '');
  rec('E4', '编码重复时在弹窗内提示后端人话（不是"创建失败"）',
    /已存在|重复|duplicate|唯一/i.test(errText), `err=${errText}`);
  await shot('E4_dup');
  // 关键：失败后弹窗必须还开着（关掉就等于让用户重填一遍）
  rec('E4', '校验失败后弹窗不关闭', (await page.locator('.rp-popup:visible').count()) > 0, '');
  // 关掉弹窗
  await page.locator('.rp-popup:visible .rp-popup__ft button').first().click();
  await sleep(400);

  /* ══════════ E5 编辑角色名 ══════════ */
  await selectByCode(ROLE_CODE);
  await page.locator('.rp-head__ops button').first().click();
  await sleep(500);
  const popup3 = page.locator('.rp-popup:visible').first();
  const renamed = ROLE_NAME + '改';
  await popup3.locator('input').nth(0).fill(renamed);
  await popup3.locator('.rp-popup__ft button').last().click();
  await sleep(1500);
  const titleAfter = await page.locator('.rp-head__title').innerText().catch(() => '');
  rec('E5', '改名后右侧标题同步更新', titleAfter.includes(renamed), `title=${titleAfter.split('\n')[0]}`);
  const leftName = await page.locator('.rp-role.is-active .rp-role__name').innerText().catch(() => '');
  rec('E5', '改名后左侧列表同步更新', leftName.includes(renamed), `left=${leftName.trim()}`);
  // 编码创建后不可改：编辑态下编码输入框必须禁用
  await page.locator('.rp-head__ops button').first().click();
  await sleep(400);
  const codeDisabled = await page.locator('.rp-popup:visible input').nth(1).isDisabled().catch(() => false);
  rec('E5', '编辑态下角色编码不可修改', codeDisabled, `disabled=${codeDisabled}`);
  await page.locator('.rp-popup:visible .rp-popup__ft button').first().click();
  await sleep(400);

  /* ══════════ E6 内置角色（admin）删除按钮禁用 ══════════ */
  const pickedAdmin = await selectByCode('admin');
  const builtinDel = page.locator('.rp-head__ops button').last();
  const disabledAttr = await builtinDel.getAttribute('disabled').catch(() => null);
  rec('E6', '内置角色 admin 的删除按钮禁用', pickedAdmin && disabledAttr !== null,
    `found=${pickedAdmin} disabled=${disabledAttr !== null ? 'yes' : 'no'}`);

  /* ══════════ E8 加成员 ══════════ */
  await selectByCode(ROLE_CODE);
  const addBtn = page.locator('.rp-members__hd button:visible');
  rec('E8', '成员区有「+ 添加成员」按钮', (await addBtn.count()) > 0, '');
  if (await addBtn.count()) {
    await addBtn.first().click();
    await sleep(1500);
    const userRow = page.locator('.rp-popup:visible .rp-user').first();
    const before = await page.locator('.rp-member').count();
    if (await userRow.count()) {
      const uname = await userRow.locator('.rp-member__name').innerText();
      await userRow.locator('button').click();
      await sleep(1500);
      const after = await page.locator('.rp-member').count();
      rec('E8', '加入成员后成员区多一人', after === before + 1,
        `${before} → ${after}（${uname.trim()}）`);
    } else {
      rec('E8', '成员选择器有可选用户', false, '列表为空');
    }
    await page.locator('.rp-popup:visible .rp-popup__ft button').first().click();
    await sleep(500);
  }
  await shot('E8_member');

  /* ══════════ E7 删除临时角色 ══════════ */
  // 有成员时后端会拒绝删除 → 先把成员移出（顺带验证 409 拦截）
  /** 点按钮 → 等确认框真的出来再点确认，返回是否成功 */
  async function confirmDialog(clickTarget) {
    await clickTarget.click();
    const dlg = page.locator('.van-dialog:visible').first();
    const ok = await dlg.waitFor({ state: 'visible', timeout: 5000 })
      .then(() => true).catch(() => false);
    if (!ok) return false;
    await dlg.locator('.van-dialog__confirm').first().click();
    return true;
  }
  /** 等 toast 消失，避免它盖住后续要点的按钮 */
  async function waitToastGone() {
    await page.locator('.van-toast:visible').first()
      .waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
    await sleep(200);
  }

  const memberCount = await page.locator('.rp-member').count();
  if (memberCount > 0) {
    await selectByCode(ROLE_CODE);
    const blockedClicked = await confirmDialog(page.locator('.rp-head__ops button').last());
    await waitToastGone();
    const stillAfterBlocked = await listHas(ROLE_CODE);
    rec('E7', '角色有成员时后端拒绝删除（列表仍在）', blockedClicked && stillAfterBlocked,
      `成员 ${memberCount} 人 → 仍在=${stillAfterBlocked}`);

    // 逐个移出成员：每轮核对人数确实下降，否则不硬转
    let guard = 0;
    while (guard++ < 5) {
      const before = await page.locator('.rp-member').count();
      if (!before) break;
      const rm = page.locator('.rp-member button:visible').first();
      if (!(await rm.count())) break;
      if (!(await confirmDialog(rm))) {
        rec('E7', '移出成员确认框未出现', false, `第 ${guard} 轮`);
        break;
      }
      await waitToastGone();
      const after = await page.locator('.rp-member').count();
      if (after >= before) {
        rec('E7', '移出成员后人数未下降', false, `${before} → ${after}`);
        break;
      }
    }
    const left = await page.locator('.rp-member').count();
    rec('E7', '成员已全部移出', left === 0, `剩余 ${left} 人`);
  }

  // 每次删之前重新点一次目标角色：删成功后页面会自动选中列表第一条，
  // 不重选就会把"下一条"当成本次目标（首版脚本就是这么误删了一个种子角色）
  const beforeDelete = await selectByCode(ROLE_CODE);
  const delClicked = await confirmDialog(page.locator('.rp-head__ops button').last());
  await waitToastGone();
  // 列表刷新有网络往返，轮询等它消失而不是固定 sleep
  let gone = false;
  for (let i = 0; i < 10; i++) {
    if (!(await listHas(ROLE_CODE))) { gone = true; break; }
    await sleep(500);
  }
  rec('E7', '临时角色已从列表消失', beforeDelete && delClicked && gone, `code=${ROLE_CODE}`);
  // 不变量：种子角色数量不能因为这次删除而减少（防"删错行"）
  const seedCodes = ['admin', 'department_head', 'team_leader', 'scheduler',
    'process_engineer', 'key_user', 'maintenance_tech', 'inspector', 'quality_engineer'];
  const missing = [];
  for (const c of seedCodes) if (!(await listHas(c))) missing.push(c);
  rec('E7', '9 个种子角色一个都没被误删', missing.length === 0,
    missing.length ? `缺失 ${missing.join(',')}` : `已核对 ${seedCodes.length} 个`);
  await shot('E7_deleted');

  /* ══════════ E9 department_head 看不到新建/编辑/删除 ══════════ */
  const dh = await loginAs('demo_ws1_leader', 'admin123');
  rec('E9', 'demo_ws1_leader 登录', dh.ok, `perms=${dh.perms}`);
  await openRoles();
  const dhCreateBtn = await page.locator('.rp-roles__hd button:visible').count();
  rec('E9', '无 PLAT:role:create 的账号看不到「+ 新建」', dhCreateBtn === 0,
    `count=${dhCreateBtn}`);
  // 该账号有 role:read 但没有 role:update/delete → 头部操作区整体不渲染
  const dhOps = await page.locator('.rp-head__ops button:visible').count();
  rec('E9', '无 role:update/delete 的账号看不到编辑/删除', dhOps === 0, `count=${dhOps}`);
  await shot('E9_dept_head');

  /* ══════════ E10 JS 错误 ══════════ */
  rec('E10', '全程无 JS 运行时错误', consoleErrors.length === 0,
    `${consoleErrors.length} error${consoleErrors.length ? '：' + consoleErrors.slice(0, 3).join(' | ') : ''}`);

  await browser.close();
  const pass = results.filter(r => r.status === 'PASS').length;
  const fail = results.filter(r => r.status === 'FAIL').length;
  console.log(`\n===== 合计 ${results.length} 项：PASS ${pass} / FAIL ${fail} =====`);
  fs.writeFileSync(path.join(SHOT, 'result.json'), JSON.stringify(results, null, 2));
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('[FATAL]', e); process.exit(1); });
