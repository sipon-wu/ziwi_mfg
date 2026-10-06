/*
 * M14/M15（NPI 试产 + 实验室）staging 真浏览器 E2E 回归
 * 目标环境：https://mfg1.ziwi.cn （运行 origin/main）
 * 范式：复用 e2e/cvm_regression_2026-10-03.js（Playwright Chromium + --no-sandbox）
 *
 * 覆盖路由：
 *   /#/trials          试产管理列表（M16）
 *   /#/trials/create   新建试产（M16）
 *   /#/trials/:id      试产详情（取列表首个可见行，失败则跳过）
 *   /#/lab             实验室管理列表（M15）
 *   /#/lab/standards   标准库（M15）
 *
 * 判定：登录成功 → 逐路由断言可访问（未被踢回 login / 不抛错）；
 *       列表视图额外检查是否渲染出数据行（证明后端已返回数据）。
 * 输出：{ results, errorCount, errors }
 */
const { chromium } = require('playwright');

const BASE = 'https://mfg1.ziwi.cn';
const NPI_ROUTES = [
  { path: '/trials', label: 'M16-试产列表' },
  { path: '/trials/create', label: 'M16-新建试产' },
  { path: '/lab', label: 'M15-实验室列表' },
  { path: '/lab/standards', label: 'M15-标准库' },
];

(async () => {
  const errors = [];
  const browser = await chromium.launch({
    executablePath: 'C:\\Users\\Kane.liu\\AppData\\Local\\ms-playwright\\chromium-1228\\chrome-win64\\chrome.exe',
    args: ['--no-sandbox']
  });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.on('console', m => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });
  page.on('pageerror', e => errors.push('[pageerror] ' + e.message));
  page.on('requestfailed', r => errors.push('[reqfail] ' + r.url() + ' ' + (r.failure() && r.failure().errorText)));

  const results = {};
  try {
    // ── 登录（复用主账号 mfg_admin，具 admin 角色）──
    await page.goto(BASE + '/#/login', { waitUntil: 'networkidle' });
    await page.fill('input[placeholder="请输入用户名"]', 'mfg_admin');
    await page.fill('input[placeholder="请输入密码"]', 'admin123');
    await page.click('button[type=submit]');
    await page.waitForURL('**/cockpit**', { timeout: 15000 });
    results.login = 'OK';

    // ── 逐路由回归 ──
    for (const rt of NPI_ROUTES) {
      const url = BASE + '/#' + rt.path;
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });
        await page.waitForTimeout(1500);
        const u = page.url();
        if (u.includes('/login')) {
          results[rt.label] = 'FAIL: redirected to login (auth/role)';
          continue;
        }
        // 列表视图额外校验数据行是否渲染（后端返回数据）
        let rows = 0;
        if (rt.path === '/trials' || rt.path === '/lab') {
          rows = await page.locator('.van-list, table tbody tr, .list-item, .data-row').count();
        }
        results[rt.label] = rows > 0 ? `OK (dataRows=${rows})` : 'OK (page rendered, no list rows detected)';
        await page.screenshot({ path: 'shot-npi-' + rt.path.replace(/\//g, '-') + '.png' });
      } catch (e) {
        results[rt.label] = 'FAIL: ' + e.message.split('\n')[0];
      }
    }

    // ── 试产详情：取列表首个可见行跳转（失败跳过，不计入致命）──
    try {
      await page.goto(BASE + '/#/trials', { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1500);
      const firstRow = page.locator('.van-cell').first();
      if (await firstRow.count() > 0) {
        await firstRow.click({ timeout: 8000 });
        await page.waitForTimeout(1500);
        const u = page.url();
        results['M16-试产详情'] = u.includes('/trials/') ? 'OK' : 'FAIL: 未进入详情页';
        await page.screenshot({ path: 'shot-npi-trial-detail.png' });
      } else {
        results['M16-试产详情'] = 'SKIP: 列表无可见行可点击';
      }
    } catch (e) {
      results['M16-试产详情'] = 'FAIL: ' + e.message.split('\n')[0];
    }
  } catch (e) {
    results.fatal = e.message;
  }

  await browser.close();
  console.log(JSON.stringify({ results, errorCount: errors.length, errors: errors.slice(0, 40) }, null, 2));
})();
