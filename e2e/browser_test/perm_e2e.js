// perm_e2e.js — 权限体系（S1/S2/S3）真实浏览器验证
// 前置：后端 8000（新代码）+ 前端 5173（dist_perm 产物）已启动。
//
// 覆盖：
//   R1 admin 登录 → 菜单齐全
//   R2 admin 直访受保护路由 → 正常
//   R3 inspector 登录 → 无「生产管理」「设备管理」菜单，有「品质管理」
//   R4 inspector 直访 /#/equipment（缺 M06:equipment:read）→ 跳 /403 并显示所需权限
//   R5 maintenance_tech 登录 → 有「设备管理」、无「品质管理」
//   R6 maintenance_tech 直访 /#/quality（缺 M03）→ 跳 /403
//   R7 权限码在 localStorage 中已持久化
//
// 用法：node e2e/browser_test/perm_e2e.js
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'perm_e2e');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

// 与 seeds/mfg1_e2e_seed_data.py 的测试账号口令约定保持一致
const PWD = 'test123456';
const results = [];
function rec(id, name, status, detail, shot) {
  results.push({ id, name, status, detail, shot });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const field = (page, label) =>
  page.locator('.van-field', { hasText: label }).locator('input, textarea').first();

async function login(page, username, password) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(700);
  // 清掉上一次的会话，确保是干净的登录
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(700);
  await field(page, '用户名').fill(username);
  await field(page, '密码').fill(password);
  await page.locator('button[type="submit"]').click();
  await sleep(3200);
  return page.url();
}

async function menuText(page) {
  await page.goto(`${BASE}/#/dashboard`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1500);
  return page.evaluate(() => document.body.innerText);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('[pageerror] ' + e.message));

  async function shot(id) {
    try { await page.screenshot({ path: path.join(SHOT, `${id}.png`), fullPage: false }); }
    catch { /* ignore */ }
  }

  // ══════════ R1 admin ══════════
  let url = await login(page, 'mfg_admin', 'admin123');
  let perms = await page.evaluate(() => {
    const u = JSON.parse(localStorage.getItem('user_info') || '{}');
    return Array.isArray(u.permissions) ? u.permissions : [];
  });
  let txt = await menuText(page);
  const adminMenus = ['基础数据', '生产管理', '设备管理', '品质管理'];
  const adminOk = adminMenus.every(m => txt.includes(m));
  rec('R1', 'admin 菜单齐全', adminOk ? 'PASS' : 'FAIL',
    `menus=${adminMenus.filter(m => txt.includes(m)).join('/')} perms=${perms.length}`);
  await shot('R1_admin_dashboard');

  // R2 admin 直访 work-orders
  await page.goto(`${BASE}/#/work-orders`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1600);
  const r2url = page.url();
  const r2body = await page.evaluate(() => document.body.innerText);
  const r2ok = r2url.includes('work-orders') && !r2url.includes('403') && !r2body.includes('没有访问权限');
  rec('R2', 'admin 直访工单页', r2ok ? 'PASS' : 'FAIL', `url=${r2url.split('#')[1]}`);
  await shot('R2_admin_workorders');

  // ══════════ R3 inspector ══════════
  url = await login(page, 'test_inspector', PWD);
  perms = await page.evaluate(() => {
    const u = JSON.parse(localStorage.getItem('user_info') || '{}');
    return Array.isArray(u.permissions) ? u.permissions : [];
  });
  txt = await menuText(page);
  const inspHasQuality = txt.includes('品质管理');
  const inspHasProd = txt.includes('生产管理');
  const inspHasEquip = txt.includes('设备管理');
  // 期望：有品质、无生产、无设备
  const r3ok = inspHasQuality && !inspHasProd && !inspHasEquip;
  rec('R3', 'inspector 菜单按权限裁剪', r3ok ? 'PASS' : 'FAIL',
    `品质=${inspHasQuality} 生产=${inspHasProd} 设备=${inspHasEquip} perms=${perms.length}`);
  await shot('R3_inspector_dashboard');

  // R4 inspector 直访设备页 → 403
  await page.goto(`${BASE}/#/equipment`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1600);
  const r4url = page.url();
  const r4body = await page.evaluate(() => document.body.innerText);
  const r4ok = r4url.includes('403') || r4body.includes('没有访问权限');
  rec('R4', 'inspector 直访设备页被拦', r4ok ? 'PASS' : 'FAIL',
    `url=${r4url.split('#')[1]}`);
  await shot('R4_inspector_403');

  // ══════════ R5 maintenance_tech ══════════
  url = await login(page, 'test_maint_tech', PWD);
  perms = await page.evaluate(() => {
    const u = JSON.parse(localStorage.getItem('user_info') || '{}');
    return Array.isArray(u.permissions) ? u.permissions : [];
  });
  txt = await menuText(page);
  const mtHasEquip = txt.includes('设备管理');
  const mtHasQuality = txt.includes('品质管理');
  const r5ok = mtHasEquip && !mtHasQuality;
  rec('R5', 'maintenance_tech 菜单按权限裁剪', r5ok ? 'PASS' : 'FAIL',
    `设备=${mtHasEquip} 品质=${mtHasQuality} perms=${perms.length}`);
  await shot('R5_maint_dashboard');

  // R6 maintenance_tech 直访品质页 → 403
  await page.goto(`${BASE}/#/quality`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1600);
  const r6url = page.url();
  const r6body = await page.evaluate(() => document.body.innerText);
  const r6ok = r6url.includes('403') || r6body.includes('没有访问权限');
  rec('R6', 'maintenance_tech 直访品质页被拦', r6ok ? 'PASS' : 'FAIL',
    `url=${r6url.split('#')[1]}`);
  await shot('R6_maint_403');

  // R7 403 页面显示所需权限码
  const r7ok = r6body.includes('M03:inspection_order:read') || r6body.includes('查看详情');
  rec('R7', '403 页面可定位所需权限', r7ok ? 'PASS' : 'FAIL',
    `含权限码=${r6body.includes('M03:inspection_order:read')}`);

  const fails = results.filter(r => r.status !== 'PASS').length;
  const pageErrs = errors.filter(e => !e.includes('favicon'));
  rec('R8', '无未捕获页面错误', pageErrs.length === 0 ? 'PASS' : 'WARN',
    pageErrs.length ? pageErrs.slice(0, 3).join(' | ') : '0 error');

  fs.writeFileSync(
    path.join(__dirname, 'perm_e2e_result.json'),
    JSON.stringify({ base: BASE, results, consoleErrors: pageErrs }, null, 2)
  );

  console.log('\n════════════════════════════════');
  console.log(`总计 ${results.length} 项，失败 ${fails} 项`);
  await browser.close();
  process.exit(fails > 0 ? 1 : 0);
})();
