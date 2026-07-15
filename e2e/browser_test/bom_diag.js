// bom_diag.js — 诊断 BOM 管理页线上真实渲染状态
const { chromium } = require('playwright');
const BASE = 'https://mfg1.ziwi.cn';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', (e) => errs.push('[pageerror] ' + e.message));

  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1200);
  await page.fill('#van-field-1-input', 'mfg_admin');
  await page.fill('#van-field-2-input', 'admin123');
  await page.click('button[type="submit"]');
  await sleep(3000);
  console.log('after-login url:', page.url());

  await page.goto(`${BASE}/#/production/boms`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(2500);
  console.log('BOM url:', page.url());

  const info = await page.evaluate(() => {
    const nav = document.querySelector('.van-nav-bar__title');
    return {
      title: nav ? nav.textContent : '(no nav title)',
      hasTable: !!document.querySelector('.bom-table'),
      hasWrap: !!document.querySelector('.bom-table-wrap'),
      hasEmpty: !!document.querySelector('.van-empty'),
      hasCell: document.querySelectorAll('.van-cell').length,
      vanList: document.querySelectorAll('.van-list').length,
      bodyText: document.body.innerText.slice(0, 240),
    };
  });
  console.log('nav title  :', info.title);
  console.log('hasTable   :', info.hasTable);
  console.log('hasWrap    :', info.hasWrap);
  console.log('hasEmpty   :', info.hasEmpty);
  console.log('van-cell # :', info.hasCell);
  console.log('van-list # :', info.vanList);
  console.log('bodyText   :', JSON.stringify(info.bodyText));
  console.log('consoleErr :', JSON.stringify(errs.slice(0, 10)));

  await browser.close();
})().catch((e) => { console.error('致命错误:', e); process.exit(1); });
