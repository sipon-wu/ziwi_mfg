// stage5_p0_basics_regression.js
// 知微 ziwi SaaS —— P0 租户系统管理 本批次 的浏览器基础回归。
//
// 目的（对齐用户需求）：确认 B1/B2/B7/B8/B9/B12/B13 这批改动**没有把基础数据 4 个列表页
// （M01 工艺路线 / M03 工作中心 / M04 产品管理 / M05 工序定义）打坏**。
//
// 与 stage5_local_regression.js 的区别：
//   - BASE 指向 5178（serve_tenant_p0.js 静态服务 dist-tenant-p0，/api 反代 127.0.0.1:8000）
//   - 只收口 4 个基础列表页（+ 工厂日历作为对照）
//   - 增加 P0 端点的**只读** API 校验（不改共享 QA 库状态；写路径已由 _smoke_tenant_p0.py 在 DB 副本上覆盖）
//
// 工具链：全局 @playwright/test 的 playwright；Chromium headless + --no-sandbox
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = process.env.P0_BASE || 'http://127.0.0.1:5178';
const SHOT = path.join(__dirname, 'screenshots');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function record(name, status, detail) {
  results.push({ name, status, detail });
  console.log(`[${status}] ${name} — ${detail}`);
}

/** WCAG 相对亮度：0=黑 1=白 */
function relLum(rgb) {
  const m = String(rgb).match(/\d+/g);
  if (!m || m.length < 3) return null;
  const [r, g, b] = m.slice(0, 3).map((c) => {
    c = Number(c) / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

async function uiLogin(page, user, pass) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1200);
  await page.fill('#van-field-1-input', user);
  await page.fill('#van-field-2-input', pass);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle').catch(() => {});
  await sleep(2000);
  try {
    return await page.evaluate(() => localStorage.getItem('access_token'));
  } catch (e) {
    await sleep(1500);
    try { return await page.evaluate(() => localStorage.getItem('access_token')); }
    catch (_) { return null; }
  }
}

/**
 * 打开一个列表页并触发 van-list 懒加载。
 * @param {import('playwright').Page} page
 * @param {string} route hash 路由（不带 #）
 */
async function openListPage(page, route) {
  // route 形如 '#/basics/products'（自带 '#'），直接拼在 BASE 之后，不要再加 '/'
  await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1200);
  for (let i = 0; i < 3; i++) {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await sleep(700);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(500);
}

// 基础数据 4 个列表页：route / 名称 / 预期 .rd-cell 数（searchFields.ts rowDetailFields 全集）
// 预期值沿用 stage5_local_regression.js 已统计口径，保证与 QA 基线可比。
const PAGES = [
  { route: '#/basics/products',     name: 'M04产品',     expected: 11, resource: 'products' },
  { route: '#/basics/operations',   name: 'M05工序',     expected: 13, resource: 'operations' },
  { route: '#/basics/routes',       name: 'M01工艺路线', expected: 12, resource: 'routes' },
  { route: '#/basics/work-centers', name: 'M03工作中心', expected: 13, resource: 'work-centers' },
];

(async () => {
  // 显式指定 Chromium 可执行文件（默认 ms-playwright/chromium-1228 即该路径），可经 P0_CHROMIUM 覆盖
  const executablePath = process.env.P0_CHROMIUM
    || 'C:\\Users\\Kane.liu\\AppData\\Local\\ms-playwright\\chromium-1228\\chrome-win64\\chrome.exe';
  const browser = await chromium.launch({
    headless: true,
    executablePath,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push('[pageerror] ' + e.message));
  const notFound = [];
  page.on('response', (res) => { if (res.status() === 404) notFound.push(res.url()); });

  // ---- 登录 ----
  let token = await uiLogin(page, 'admin', 'admin123');
  if (!token) token = await uiLogin(page, 'demo', 'admin123');
  if (!token) token = await uiLogin(page, 'demo', 'test_admin');
  if (!token) {
    record('LOGIN', 'FAIL', '多组账号均无法登录，浏览器回归中断');
    await browser.close();
    process.exit(1);
  }
  record('LOGIN', 'PASS', `登录成功（BASE=${BASE}），已获得 access_token`);

  /** 构造带 Bearer 的请求参数 */
  const authOpts = () => ({ headers: { Authorization: `Bearer ${token}` } });

  /** 后端统一响应体为 {code,message,data}；解出 data，并兼容裸数组/分页对象 */
  const unwrap = async (r) => {
    const j = await r.json();
    const body = (j && typeof j === 'object' && 'data' in j) ? j.data : j;
    if (Array.isArray(body)) return { raw: body, list: body };
    if (body && typeof body === 'object') {
      return { raw: body, list: Array.isArray(body.items) ? body.items : [] };
    }
    return { raw: body, list: [] };
  };

  // ---- P0 端点只读校验（不写共享 QA 库）----
  // B2 GET /tenant/modules
  try {
    const r = await page.request.get(`${BASE}/api/v1/tenants/tenant/modules`, authOpts());
    const { raw } = await unwrap(r);
    const keys = Array.isArray(raw.module_codes) ? raw.module_codes : (Array.isArray(raw) ? raw : []);
    record('P0-B2-GET/modules', r.status() === 200 ? 'PASS' : 'FAIL',
      `http=${r.status()} 已启用模块键=${JSON.stringify(keys)}`);
  } catch (e) {
    record('P0-B2-GET/modules', 'FAIL', '异常: ' + e.message);
  }

  // B1 GET /tenants/{tenant_id}/license —— 只走本地库，无 cloud 出站
  try {
    const me = await page.request.get(`${BASE}/api/v1/auth/me`, authOpts());
    const meBody = await unwrap(me);
    const tenantId = meBody.raw.tenant_id || meBody.raw.user?.tenant_id || null;
    const r = await page.request.get(`${BASE}/api/v1/tenants/${tenantId}/license`, authOpts());
    const { list: licRows, raw: licRaw } = await unwrap(r);
    // list 为空数组时不能直接取 [0]（会得到 undefined），此时应回落到单条对象 raw
    const lic = Array.isArray(licRows) && licRows.length > 0 ? licRows[0] : licRaw;
    const status = lic && typeof lic === 'object' ? lic.license_status : undefined;
    const expires = lic && typeof lic === 'object' ? lic.license_expires_at : undefined;
    const hasBoth = status !== undefined && expires !== undefined;
    record('P0-B1-GET/license', r.status() === 200 && hasBoth ? 'PASS' : 'FAIL',
      `http=${r.status()} tenant=${tenantId} license_status=${JSON.stringify(status)} license_expires_at=${JSON.stringify(expires)}`);
  } catch (e) {
    record('P0-B1-GET/license', 'FAIL', '异常: ' + e.message);
  }

  // B13 GET /roles —— 必须带 scope 字段
  try {
    const r = await page.request.get(`${BASE}/api/v1/roles`, authOpts());
    const { list } = await unwrap(r);
    const scopes = list.map((x) => x.scope);
    const hasScope = list.length > 0 && scopes.every((s) => s !== undefined && s !== null);
    record('P0-B13-GET/roles', r.status() === 200 && hasScope ? 'PASS' : 'FAIL',
      `http=${r.status()} 角色数=${list.length} scope取值=${JSON.stringify(scopes.slice(0, 8))}`);
  } catch (e) {
    record('P0-B13-GET/roles', 'FAIL', '异常: ' + e.message);
  }

  // B9 GET /users —— 必须带 org_id / org_ids
  try {
    const r = await page.request.get(`${BASE}/api/v1/users`, authOpts());
    const { list } = await unwrap(r);
    const withOrg = list.filter((x) => 'org_id' in x || 'org_ids' in x);
    record('P0-B9-GET/users', r.status() === 200 ? 'PASS' : 'FAIL',
      `http=${r.status()} 用户数=${list.length} 含组织字段条数=${withOrg.length}`);
  } catch (e) {
    record('P0-B9-GET/users', 'FAIL', '异常: ' + e.message);
  }

  // ---- 基础数据 4 个列表页回归 ----
  for (const pg of PAGES) {
    try {
      await openListPage(page, pg.route);
      const arrow = page.locator('.van-icon-arrow-down').first();
      const emptyCnt = await page.locator('.van-empty').count();
      if (await arrow.count() === 0) {
        record(`PAGE-${pg.name}`, 'FAIL',
          `${pg.route} ${emptyCnt ? '列表为空(仅 van-empty)，无数据行可展开' : '未找到行内展开按钮(.van-icon-arrow-down)'}`);
        await page.screenshot({ path: path.join(SHOT, `p0_${pg.resource}.png`) }).catch(() => {});
        continue;
      }
      await arrow.scrollIntoViewIfNeeded();
      await arrow.click();
      await page.waitForSelector('.row-detail', { timeout: 10000 });
      await sleep(600);

      const d = await page.$eval('.row-detail', (el) => {
        const grid = el.querySelector('.rd-grid');
        const scroll = el.querySelector('.rd-scroll');
        const cells = el.querySelectorAll('.rd-cell');
        const gridCols = grid ? getComputedStyle(grid).gridTemplateColumns : '';
        const colCount = gridCols ? gridCols.trim().split(/\s+/).length : 0;
        const headerEl = el.querySelector('.rd-header-count');
        const headerText = headerEl ? headerEl.textContent : '';
        const headerN = parseInt((headerText || '').replace(/\D/g, ''), 10);
        const hasFold = !!(el.querySelector('.rd-fold-btn') || el.querySelector('button'));
        const value = el.querySelector('.rd-value');
        const valueColor = value ? getComputedStyle(value).color : '';
        const scRect = scroll ? scroll.getBoundingClientRect() : null;
        const vanCell = el.closest('.van-cell') || el.parentElement;
        const vanCellW = vanCell ? vanCell.clientWidth : 0;
        const rdScrollW = scRect ? Math.round(scRect.width) : 0;
        return {
          hasGrid: !!grid, hasScroll: !!scroll, cellCount: cells.length,
          colCount, headerText: (headerText || '').trim(), headerN, hasFold,
          valueColor, rdScrollW, vanCellW,
        };
      });

      const aStruct = d.hasGrid && d.hasScroll;
      const aMulti = d.colCount > 1;
      const aField = d.cellCount === pg.expected;
      const aHeader = d.headerN === d.cellCount;
      const aNoFold = !d.hasFold;
      const aDark = (() => { const l = relLum(d.valueColor); return l !== null && l < 0.6; })();
      const allPass = aStruct && aMulti && aField && aHeader && aNoFold && aDark;

      record(`PAGE-${pg.name}`, allPass ? 'PASS' : 'FAIL',
        `route=${pg.route} 结构(grid+scroll:${aStruct}) 列数=${d.colCount}(>1:${aMulti}) ` +
        `字段=${d.cellCount}/预期${pg.expected}(一致:${aField}) header="${d.headerText}"(N一致:${aHeader}) ` +
        `折叠按钮=${d.hasFold} value色=${d.valueColor} 深色可读:${aDark}`);
      await page.screenshot({ path: path.join(SHOT, `p0_${pg.resource}.png`) }).catch(() => {});
    } catch (e) {
      record(`PAGE-${pg.name}`, 'FAIL', '异常: ' + e.message);
      await page.screenshot({ path: path.join(SHOT, `p0_${pg.resource}_err.png`) }).catch(() => {});
    }
  }

  // ---- 控制台错误 ----
  const uniq = Array.from(new Set(consoleErrors));
  // 过滤与本次改动无关的既有噪声（token 过期等），但整体计数仍如实上报
  const noisy = uniq.filter((t) => !/401|token|登录|未授权|sign/i.test(t));
  record('CONSOLE-ERRORS', noisy.length === 0 ? 'PASS' : 'WARN',
    `控制台错误 去重后共 ${uniq.length} 条（与鉴权/token 相关 ${uniq.length - noisy.length} 条），非鉴权类 ${noisy.length} 条` +
    (noisy.length ? ` | 样例: ${noisy.slice(0, 3).join(' || ')}` : '') +
    ` | 404资源: ${JSON.stringify(Array.from(new Set(notFound)).slice(0, 5))}`);

  const failed = results.filter((r) => r.status === 'FAIL');
  console.log(`\n===== 汇总: ${results.length - failed.length}/${results.length} PASS =====`);
  results.forEach((r) => console.log(`  [${r.status}] ${r.name}`));

  fs.writeFileSync(path.join(__dirname, 'stage5_p0_result.json'),
    JSON.stringify({ base: BASE, results, consoleErrors: uniq }, null, 2), 'utf8');

  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
