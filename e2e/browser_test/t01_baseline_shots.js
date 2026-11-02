// t01_baseline_shots.js — T01（令牌与基础件）四视口基线截图 + 溢出度量
//
// 用途：
//   1. 改动前（before）留证：pages/basics/ 6 页 × 四视口各一张截图 + scrollWidth/innerWidth
//   2. 改动后（after）复跑同一脚本，逐页对比「无内容裁切、无横向溢出」
//
// 前置：后端 8000 + 前端 5173 已启动
// 用法：
//   node e2e/browser_test/t01_baseline_shots.js before
//   node e2e/browser_test/t01_baseline_shots.js after
//   对比：node e2e/browser_test/t01_baseline_shots.js compare
//
// 输出：
//   e2e/browser_test/screenshots/t01-baseline/<phase>/<page>--<w>x<h>.png
//   e2e/browser_test/screenshots/t01-baseline/<phase>/metrics.json
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const ROOT = path.join(__dirname, 'screenshots', 't01-baseline');
// 本地 ziwi_alpha.db 的可用管理员账号（mfg_admin 属于 staging 种子）
const USER = process.env.E2E_USER || 'admin';
const PASS = process.env.E2E_PASS || 'admin123';

const VIEWPORTS = [
  { name: '412x915', width: 412, height: 915 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '1024x768', width: 1024, height: 768 },
  { name: '1440x900', width: 1440, height: 900 },
];

// pages/basics/ 的 6 个页面（与 router/index.ts 中路径一致）
const PAGES = [
  { id: 'CalendarView', route: '/basics/calendar', title: '工厂日历' },
  { id: 'OperationList', route: '/basics/operations', title: '工序定义' },
  { id: 'ProductList', route: '/basics/products', title: '产品管理' },
  { id: 'RouteEditor', route: '/basics/route-editor/1', title: '工序编排' },
  { id: 'RouteList', route: '/basics/routes', title: '工艺路线' },
  { id: 'WorkCenterList', route: '/basics/work-centers', title: '工作中心' },
];

const phase = (process.argv[2] || 'before').toLowerCase();

function ensureDir(p) {
  if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
}

async function login(page) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(600);
  await page.fill('input[placeholder="请输入用户名"]', USER);
  await page.fill('input[placeholder="请输入密码"]', PASS);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2600);
  return await page.evaluate(() => localStorage.getItem('access_token'));
}

/**
 * 采集一页的布局度量。
 * @param {import('playwright').Page} page
 */
async function measure(page) {
  return await page.evaluate(() => {
    const de = document.documentElement;
    const innerWidth = window.innerWidth;
    // 找出所有溢出到视口右侧的元素（排除被 overflow 裁剪的容器内部元素）
    const overflowers = [];
    const walk = (el) => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > innerWidth + 1) {
        overflowers.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || '').toString().slice(0, 80),
          right: Math.round(r.right),
        });
      }
      for (const c of el.children) walk(c);
    };
    walk(document.body);
    return {
      formFactor: de.dataset.formFactor || null,
      glove: de.dataset.glove || null,
      innerWidth,
      scrollWidth: de.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      bodyHeight: document.body.scrollHeight,
      overflowX: de.scrollWidth - innerWidth,
      overflowers: overflowers.slice(0, 8),
      overflowCount: overflowers.length,
      textLen: document.body.innerText.trim().length,
      touchMin: getComputedStyle(de).getPropertyValue('--ziwi-touch-min').trim(),
    };
  });
}

async function shot(page, file) {
  try {
    await page.screenshot({ path: file, fullPage: false });
    return true;
  } catch {
    return false;
  }
}

(async () => {
  const outDir = path.join(ROOT, phase);
  ensureDir(outDir);

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const consoleErrors = [];
  const results = [];

  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(`[${vp.name}] ${m.text()}`);
    });
    page.on('pageerror', (e) => consoleErrors.push(`[${vp.name}][pageerror] ${e.message}`));

    const token = await login(page);
    if (!token) {
      console.log(`[FAIL] 登录失败 @${vp.name}`);
    }

    for (const pg of PAGES) {
      const errBefore = consoleErrors.length;
      let row = {
        phase,
        viewport: vp.name,
        page: pg.id,
        title: pg.title,
        route: pg.route,
      };
      try {
        await page.goto(`${BASE}/#${pg.route}`, { waitUntil: 'networkidle', timeout: 30000 });
        await page.waitForTimeout(1100);
        const m = await measure(page);
        const file = path.join(outDir, `${pg.id}--${vp.name}.png`);
        const okShot = await shot(page, file);
        const newErr = consoleErrors.slice(errBefore);
        row = {
          ...row,
          ...m,
          screenshot: okShot ? path.relative(ROOT, file).replace(/\\/g, '/') : null,
          errors: newErr.slice(0, 3),
          ok: m.scrollWidth <= m.innerWidth + 1,
        };
        const flag = row.ok ? 'PASS' : 'FAIL';
        console.log(
          `[${flag}] ${phase} ${vp.name} ${pg.id} — scrollWidth=${m.scrollWidth} innerWidth=${m.innerWidth} ` +
            `overflow=${m.overflowX} text=${m.textLen} formFactor=${m.formFactor} touchMin=${m.touchMin}`,
        );
        if (m.overflowCount) {
          console.log(
            `      ↳ 溢出元素 ${m.overflowCount} 个: ` +
              m.overflowers.map((o) => `${o.tag}.${o.cls}@${o.right}`).join(' | '),
          );
        }
      } catch (e) {
        row = { ...row, ok: false, error: (e.message || '').slice(0, 200) };
        console.log(`[FAIL] ${phase} ${vp.name} ${pg.id} — ${row.error}`);
      }
      results.push(row);
    }
    await ctx.close();
  }

  await browser.close();

  const metricsFile = path.join(outDir, 'metrics.json');
  fs.writeFileSync(
    metricsFile,
    JSON.stringify({ phase, base: BASE, recordedAt: new Date().toISOString(), results }, null, 2),
    'utf8',
  );
  console.log(`\n[写出] ${path.relative(process.cwd(), metricsFile)}`);
  const failed = results.filter((r) => !r.ok).length;
  console.log(`[汇总] ${phase}: ${results.length - failed}/${results.length} 页无横向溢出`);
  process.exitCode = failed ? 1 : 0;
})();
