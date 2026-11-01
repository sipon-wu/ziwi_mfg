// local_alpha_smoke.js — 本地 Alpha 真实浏览器冒烟（Playwright/Chromium，headless）
// 前置：后端 8000（uvicorn）+ 前端 5173（vite dev，代理 /api→8000）已在跑
// 覆盖：UI 登录 mfg_admin → 逐模块导航（dashboard/工单/品质/NCR/产品/物料/设备/安灯/能碳）
//       → 校验页面渲染 + 控制台错误 + 截图
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'local_alpha');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('[pageerror] ' + e.message));
  page.on('requestfailed', r => consoleErrors.push('[reqfail] ' + r.url()));

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ── TC-01 登录 ──
  try {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(800);
    await page.fill('input[placeholder="请输入用户名"]', 'mfg_admin');
    await page.fill('input[placeholder="请输入密码"]', 'admin123');
    await page.click('button[type="submit"]');
    await sleep(3000);
    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    const url = page.url();
    const ok = !!token;
    rec('TC-01', 'UI 登录 mfg_admin', ok ? 'PASS' : 'FAIL', `token=${!!token}, url=${url.split('#')[1] || '/'}`);
  } catch (e) {
    rec('TC-01', 'UI 登录 mfg_admin', 'FAIL', e.message.slice(0, 120));
  }

  // ── TC-02~ 逐模块导航 ──
  const modules = [
    ['TC-02', '驾驶舱', '/dashboard'],
    ['TC-03', '生产工单', '/work-orders'],
    ['TC-04', '品质管理(检验)', '/quality'],
    ['TC-05', '不合格评审 NCR', '/quality/ncr'],
    ['TC-06', '产品管理', '/basics/products'],
    ['TC-07', '工艺路线', '/basics/routes'],
    ['TC-08', '工厂日历', '/basics/calendar'],
    ['TC-09', '设备管理', '/equipment'],
    ['TC-10', '安灯管理', '/andon'],
    ['TC-11', '能碳管理', '/energy'],
    ['TC-12', '物料主数据(WMS)', '/wms/materials'],
    ['TC-13', '仓库结构(WMS)', '/wms/warehouse-tree'],
    ['TC-14', 'FMEA', '/quality/fmea'],
    ['TC-15', 'SPC控制限', '/quality/spc/control-limits'],
    ['TC-16', '试产管理', '/trials'],
    ['TC-17', '实验室', '/lab'],
  ];

  for (const [id, name, route] of modules) {
    const errBefore = consoleErrors.length;
    try {
      await page.goto(`${BASE}/#${route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(1200);
      const hash = await page.evaluate(() => location.hash);
      // 若被路由守卫重定向到 /login 或 /dashboard，说明未登录/无权限
      const redirected = hash.includes('login');
      const hasBody = await page.evaluate(() => document.body.innerText.trim().length > 0);
      const newErrors = consoleErrors.slice(errBefore);
      const ok = !redirected && hasBody && newErrors.length === 0;
      await page.screenshot({ path: path.join(SHOT, `${id}.png`), fullPage: false });
      rec(id, name, ok ? 'PASS' : 'FAIL',
        `hash=${hash}${redirected ? ' [被重定向]' : ''}, errors=${newErrors.length}`);
      if (newErrors.length) console.log('      ↳ ' + newErrors.join(' | ').slice(0, 200));
    } catch (e) {
      rec(id, name, 'FAIL', e.message.slice(0, 120));
    }
  }

  // ── 汇总 ──
  const pass = results.filter(r => r.status === 'PASS').length;
  const fail = results.filter(r => r.status === 'FAIL').length;
  console.log(`\n结果：${pass} PASS / ${fail} FAIL`);
  console.log(`控制台错误总数：${consoleErrors.length}`);
  if (consoleErrors.length) console.log('  ' + consoleErrors.slice(0, 10).join('\n  '));

  await browser.close();
  process.exit(fail ? 1 : 0);
})();
