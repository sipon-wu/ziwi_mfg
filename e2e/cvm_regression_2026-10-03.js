const { chromium } = require('playwright');

const BASE = 'https://mfg1.ziwi.cn';
const ROUTES = [
  '/dashboard', '/cockpit', '/basics/operations', '/wms/materials',
  '/andon', '/work-orders', '/basics/products', '/wms/stock-query'
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
    await page.goto(BASE + '/#/login', { waitUntil: 'networkidle' });
    await page.fill('input[placeholder="请输入用户名"]', 'mfg_admin');
    await page.fill('input[placeholder="请输入密码"]', 'admin123');
    await page.click('button[type=submit]');
    await page.waitForURL('**/cockpit**', { timeout: 15000 });
    results.login = 'OK';
    await page.screenshot({ path: 'shot-01-cockpit.png' });

    for (const r of ROUTES) {
      const url = BASE + '/#' + r;
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });
        await page.waitForTimeout(1200);
        const u = page.url();
        if (u.includes('/login')) { results[r] = 'FAIL: redirected to login (auth/role)'; }
        else { results[r] = 'OK'; await page.screenshot({ path: 'shot-' + r.replace(/\//g, '-') + '.png' }); }
      } catch (e) { results[r] = 'FAIL: ' + e.message.split('\n')[0]; }
    }

    // Copilot (E1) round-trip
    try {
      await page.goto(BASE + '/#/dashboard', { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(800);
      await page.click('.ai-copilot', { timeout: 8000 });
      await page.waitForSelector('.copilot-drawer', { state: 'visible', timeout: 8000 });
      await page.fill('.cd-input-field', '昨天产量是多少');
      await page.click('.cd-send');
      await page.waitForSelector('.msg-assistant', { timeout: 25000 });
      results.copilot = 'OK (assistant reply rendered)';
      await page.screenshot({ path: 'shot-copilot.png' });
    } catch (e) { results.copilot = 'FAIL: ' + e.message.split('\n')[0]; }
  } catch (e) {
    results.fatal = e.message;
  }

  await browser.close();
  console.log(JSON.stringify({ results, errorCount: errors.length, errors: errors.slice(0, 40) }, null, 2));
})();
