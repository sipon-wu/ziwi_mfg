// role_perm_ui_e2e.js — 角色权限配置界面（系统管理 → 角色权限）真实浏览器验证
// 前置：后端 8000（新代码）+ 前端 5173（新 dist）已启动。
//
// 覆盖：
//   U1 admin 进入 /#/system/roles，左侧角色列表渲染（含系统菜单入口）
//   U2 权限树按模块/资源/动作三层渲染，动作中文标签正确
//   U3 勾选一个动作 → 出现「有未保存的改动」
//   U4 保存 → 提示成功，且后端 GET /roles/{id} 真实落库
//   U5 刷新页面重新进入 → 勾选状态持久（真落库，非前端缓存）
//   U6 切换数据范围 → 保存 → 后端 roles.scope 变更
//   U7 搜索过滤：输入「工单」只保留命中模块/资源
//   U8 「重置」回到上次保存状态
//   U9 无权限账号（inspector）直访 /#/system/roles → 跳 403
//
// 安全约束：全程只操作测试脚本**自己创建**的临时角色 __e2e_role，
// 结束前删除；不触碰 team_leader / inspector 等真实角色的授权。
//
// 用法：node e2e/browser_test/role_perm_ui_e2e.js
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const API = 'http://127.0.0.1:8000/api/v1';
const SHOT = path.join(__dirname, 'screenshots', 'role_perm_ui');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

const PWD = 'test123456';
const TMP_CODE = '__e2e_role';
const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const field = (page, label) =>
  page.locator('.van-field', { hasText: label }).locator('input, textarea').first();

async function login(page, username, password) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(600);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(600);
  await field(page, '用户名').fill(username);
  await field(page, '密码').fill(password);
  await page.locator('button[type="submit"]').click();
  await sleep(3200);
}

function token(page) {
  return page.evaluate(() => localStorage.getItem('access_token') || '');
}

async function api(page, method, url, body) {
  const t = await token(page);
  const res = await fetch(`${API}${url}`, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* ignore */ }
  return { status: res.status, json, text };
}

/** 清掉可能残留的临时角色（上一次中断留下的） */
async function purgeTmpRole(page) {
  const r = await api(page, 'GET', '/roles?page=1&page_size=100');
  const items = r.json?.data?.items || [];
  for (const it of items) {
    if (it.code === TMP_CODE) {
      await api(page, 'DELETE', `/roles/${it.id}`);
    }
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));

  async function shot(id) {
    try { await page.screenshot({ path: path.join(SHOT, `${id}.png`) }); } catch { /* ignore */ }
  }

  let tmpRoleId = null;

  try {
    // ══════════ 登录 admin ══════════
    await login(page, 'mfg_admin', 'admin123');
    await purgeTmpRole(page);

    // 用 API 造一个临时角色，避免改动真实角色
    const created = await api(page, 'POST', '/roles', {
      name: 'E2E 临时角色', code: TMP_CODE, description: 'role_perm_ui_e2e 自动创建，结束即删',
    });
    tmpRoleId = created.json?.data?.id;
    rec('U0', '准备临时角色', tmpRoleId ? 'PASS' : 'FAIL', `role_id=${tmpRoleId}`);

    // ══════════ U1 进入页面 ══════════
    await page.goto(`${BASE}/#/system/roles`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(2500);
    const body1 = await page.evaluate(() => document.body.innerText);
    const roleCards = await page.locator('.rp-role').count();
    const u1ok = roleCards >= 10 && body1.includes('权限') && !page.url().includes('403');
    rec('U1', '角色权限页渲染', u1ok ? 'PASS' : 'FAIL',
      `角色卡片=${roleCards} url=${page.url().split('#')[1]}`);
    await shot('U1_page');

    // ══════════ U2 三层层级与中文标签 ══════════
    const moduleCount = await page.locator('.rp-module').count();
    const hasWorkOrderRes = await page.locator('.rp-res__name', { hasText: /^工单$/ }).count();
    const actLabels = await page.locator('.rp-act').allInnerTexts();
    const hasReadLabel = actLabels.includes('查看');
    const hasCreateLabel = actLabels.includes('新建');
    const u2ok = moduleCount >= 10 && hasWorkOrderRes >= 1 && hasReadLabel && hasCreateLabel;
    rec('U2', '模块/资源/动作三层 + 中文标签', u2ok ? 'PASS' : 'FAIL',
      `模块=${moduleCount} 工单资源=${hasWorkOrderRes} 查看=${hasReadLabel} 新建=${hasCreateLabel}`);
    await shot('U2_tree');

    // ══════════ 选中临时角色 ══════════
    await page.locator('.rp-role', { hasText: TMP_CODE }).first().click();
    await sleep(1200);
    const statText = await page.locator('.rp-head__stats').innerText();
    rec('U2b', '选中临时角色（初始 0 项）', /\/\s*332/.test(statText) ? 'PASS' : 'FAIL',
      statText.replace(/\s+/g, ' '));

    // ══════════ U3 勾选 → dirty ══════════
    // M01 生产管理默认展开（前两个模块默认展开：M00 / M01）
    const m01Open = await page.locator('.rp-res__name', { hasText: /^工单$/ }).count();
    if (!m01Open) {
      await page.locator('.rp-module__hd', { hasText: '生产管理' }).first().click();
      await sleep(600);
    }
    const woRes = page.locator('.rp-res').filter({
      has: page.locator('.rp-res__name', { hasText: /^工单$/ }),
    }).first();
    await woRes.locator('.rp-act', { hasText: '查看' }).first().click();
    await sleep(600);
    const dirtyTxt = await page.locator('.rp-actions').innerText();
    const u3ok = dirtyTxt.includes('有未保存的改动');
    rec('U3', '勾选后出现未保存提示', u3ok ? 'PASS' : 'FAIL',
      dirtyTxt.replace(/\s+/g, ' ').slice(0, 60));
    await shot('U3_dirty');

    // ══════════ U4 保存并落库 ══════════
    await page.locator('.rp-btn--primary', { hasText: /保存/ }).click();
    await sleep(2200);
    const body4 = await page.evaluate(() => document.body.innerText);
    const detail = await api(page, 'GET', `/roles/${tmpRoleId}`);
    const savedPerms = detail.json?.data?.permissions || [];
    const u4ok = savedPerms.length === 1 && savedPerms[0] === 'M01:work_order:read';
    rec('U4', '保存并真实落库', u4ok ? 'PASS' : 'FAIL',
      `后端权限=${JSON.stringify(savedPerms)} toast=${body4.includes('已保存')}`);
    await shot('U4_saved');

    // ══════════ U5 刷新后状态持久 ══════════
    await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
    await sleep(2600);
    await page.locator('.rp-role', { hasText: TMP_CODE }).first().click();
    await sleep(1400);
    const stat5 = await page.locator('.rp-head__stats').innerText();
    const checkedActs = await page.locator('.rp-act.is-checked').count();
    const u5ok = checkedActs === 1 && /^[^\d]*1/.test(stat5.replace(/\s+/g, ' '));
    rec('U5', '刷新后勾选持久', u5ok ? 'PASS' : 'FAIL',
      `已勾选标签=${checkedActs} 统计=${stat5.replace(/\s+/g, ' ')}`);

    // ══════════ U6 数据范围 ══════════
    await page.locator('.rp-scope__opt', { hasText: '本部门及下级' }).first().click();
    await sleep(400);
    await page.locator('.rp-btn--primary', { hasText: /保存/ }).click();
    await sleep(2200);
    const detail6 = await api(page, 'GET', `/roles/${tmpRoleId}`);
    const u6ok = detail6.json?.data?.scope === 'DEPT_CHILD';
    rec('U6', '数据范围保存', u6ok ? 'PASS' : 'FAIL',
      `scope=${detail6.json?.data?.scope}`);
    await shot('U6_scope');

    // ══════════ U7 搜索过滤 ══════════
    await page.locator('.rp-search').fill('工单');
    await sleep(800);
    const filteredModules = await page.locator('.rp-module').count();
    const filteredRes = await page.locator('.rp-res__name').allInnerTexts();
    const u7ok = filteredModules < moduleCount && filteredRes.some((t) => t.includes('工单'));
    rec('U7', '搜索过滤生效', u7ok ? 'PASS' : 'FAIL',
      `模块 ${moduleCount}→${filteredModules}；资源=${filteredRes.slice(0, 6).join('/')}`);
    await shot('U7_search');
    await page.locator('.rp-search').fill('');
    await sleep(600);

    // ══════════ U8 重置 ══════════
    // 先再勾一个（制造 dirty），再点重置
    // 注意：搜索时会强制展开命中模块，清空后展开状态保留 —— 这里先探测再决定是否点开，
    // 无条件点一次会把已展开的模块收起来。
    const woVisible = await page
      .locator('.rp-res__name', { hasText: /^工单$/ })
      .first()
      .isVisible()
      .catch(() => false);
    if (!woVisible) {
      await page.locator('.rp-module__hd', { hasText: '生产管理' }).first().click();
      await sleep(500);
    }
    const woRes8 = page.locator('.rp-res').filter({
      has: page.locator('.rp-res__name', { hasText: /^工单$/ }),
    }).first();
    await woRes8.locator('.rp-act', { hasText: '新建' }).first().click();
    await sleep(500);
    const dirtyBefore = (await page.locator('.rp-actions').innerText()).includes('有未保存的改动');
    await page.locator('.rp-btn--ghost', { hasText: '重置' }).click();
    await sleep(700);
    const afterReset = await page.locator('.rp-actions').innerText();
    const checkedAfterReset = await page.locator('.rp-act.is-checked').count();
    const u8ok = dirtyBefore && afterReset.includes('改动已保存') && checkedAfterReset === 1;
    rec('U8', '重置回到已保存状态', u8ok ? 'PASS' : 'FAIL',
      `dirty=${dirtyBefore} 重置后勾选=${checkedAfterReset}`);

    // ══════════ U9 无权限账号被拦 ══════════
    await login(page, 'test_inspector', PWD);
    await page.goto(`${BASE}/#/system/roles`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(2000);
    const u9url = page.url();
    const u9body = await page.evaluate(() => document.body.innerText);
    const u9ok = u9url.includes('403') || u9body.includes('没有访问权限');
    rec('U9', 'inspector 直访角色权限页被拦', u9ok ? 'PASS' : 'FAIL',
      `url=${u9url.split('#')[1]}`);
    await shot('U9_403');
  } catch (e) {
    rec('EX', '脚本异常', 'FAIL', String(e && e.message ? e.message : e).slice(0, 200));
  } finally {
    // ── 清理临时角色（用 admin 再登一次）──
    try {
      await login(page, 'mfg_admin', 'admin123');
      if (tmpRoleId) {
        const d = await api(page, 'DELETE', `/roles/${tmpRoleId}`);
        rec('CL', '清理临时角色', d.status === 200 ? 'PASS' : 'WARN',
          `HTTP ${d.status} ${d.text.slice(0, 80)}`);
      }
      await purgeTmpRole(page);
    } catch (e) {
      rec('CL', '清理临时角色', 'WARN', String(e).slice(0, 120));
    }
  }

  const fails = results.filter((r) => r.status === 'FAIL').length;
  const pageErrs = errors.filter((e) => !e.includes('favicon'));
  rec('UZ', '无未捕获页面错误', pageErrs.length === 0 ? 'PASS' : 'WARN',
    pageErrs.length ? pageErrs.slice(0, 3).join(' | ') : '0 error');

  fs.writeFileSync(
    path.join(__dirname, 'role_perm_ui_e2e_result.json'),
    JSON.stringify({ base: BASE, results, consoleErrors: pageErrs }, null, 2)
  );
  console.log('\n════════════════════════════════');
  console.log(`总计 ${results.length} 项，失败 ${fails} 项`);
  await browser.close();
  process.exit(fails > 0 ? 1 : 0);
})();
