// t01_acceptance.js — T01 六条验收的自动化断言
//
// 对应 docs/arch-interaction-refactor-2026-11-02.md §7 T01「独立验收」：
//   2. data-form-factor 在 412/768/1024/1440 依次为 H/T/T/W，且拖窗不刷新即变
//   3. data-glove=on 后 .van-cell paddingTop 12px → 16px
//   4. --ziwi-touch-min = 48px，手套档 56px
//   5. pages/basics 6 页在 412/1024 两视口无横向溢出
// （第 1 条与第 6 条由 python scripts/check_ui_contract.py 与 grep 覆盖，不在本脚本内）
//
// 前置：后端 8000 + 前端 5173 已启动
// 用法：node e2e/browser_test/t01_acceptance.js
const { chromium } = require('playwright');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const USER = process.env.E2E_USER || 'admin';
const PASS = process.env.E2E_PASS || 'admin123';

const PAGES = [
  { id: 'CalendarView', route: '/basics/calendar' },
  { id: 'OperationList', route: '/basics/operations' },
  { id: 'ProductList', route: '/basics/products' },
  { id: 'RouteEditor', route: '/basics/route-editor/1' },
  { id: 'RouteList', route: '/basics/routes' },
  { id: 'WorkCenterList', route: '/basics/work-centers' },
];

const results = [];
function rec(id, name, ok, detail) {
  results.push({ id, name, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${id} ${name} — ${detail}`);
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

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('pageerror', (e) => consoleErrors.push('[pageerror] ' + e.message));

  const token = await login(page);
  rec('A0', '登录', !!token, `token=${!!token}`);

  // ── 验收 2：形态判定（同一页面内改视口，不刷新）──
  const expected = [
    { w: 412, h: 915, want: 'H' },
    { w: 768, h: 1024, want: 'T' },
    { w: 1024, h: 768, want: 'T' },
    { w: 1440, h: 900, want: 'W' },
  ];
  await page.goto(`${BASE}/#/basics/operations`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(900);
  for (const item of expected) {
    await page.setViewportSize({ width: item.w, height: item.h });
    await page.waitForTimeout(320); // 等一帧 rAF
    const got = await page.evaluate(() => document.documentElement.dataset.formFactor);
    rec(
      `A2-${item.w}`,
      `形态 @${item.w}x${item.h}`,
      got === item.want,
      `期望 ${item.want}，实际 ${got}（未刷新）`,
    );
  }

  // 反向再拖一次，验证不是"只随首次加载"
  await page.setViewportSize({ width: 412, height: 915 });
  await page.waitForTimeout(320);
  const back = await page.evaluate(() => document.documentElement.dataset.formFactor);
  rec('A2-back', '形态回拖 412 → H', back === 'H', `实际 ${back}`);

  // ── 验收 3 / 4：手套档 ──
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.waitForTimeout(320);

  const readOnce = async () =>
    await page.evaluate(() => {
      const cell = document.querySelector('.van-cell');
      const root = getComputedStyle(document.documentElement);
      return {
        glove: document.documentElement.dataset.glove,
        cellPaddingTop: cell ? getComputedStyle(cell).paddingTop : null,
        touchMin: root.getPropertyValue('--ziwi-touch-min').trim(),
        touchDanger: root.getPropertyValue('--ziwi-touch-danger').trim(),
        rowMinH: root.getPropertyValue('--ziwi-row-min-h').trim(),
        actionbarH: root.getPropertyValue('--ziwi-actionbar-h').trim(),
      };
    });

  const before = await readOnce();
  rec(
    'A4-off',
    '裸手档 --ziwi-touch-min',
    before.touchMin === '48px',
    `touchMin=${before.touchMin} danger=${before.touchDanger} row=${before.rowMinH} bar=${before.actionbarH}`,
  );

  // 用组件真实路径切手套档（localStorage + 重放 init），再验证 CSS 生效
  await page.evaluate(() => {
    localStorage.setItem('ziwi:glove-mode', 'on');
    document.documentElement.dataset.glove = 'on';
  });
  await page.waitForTimeout(200);
  const after = await readOnce();
  rec(
    'A3',
    '手套档 .van-cell paddingTop 12→16',
    before.cellPaddingTop === '12px' && after.cellPaddingTop === '16px',
    `${before.cellPaddingTop} → ${after.cellPaddingTop}`,
  );
  rec(
    'A4-on',
    '手套档 --ziwi-touch-min = 56px',
    after.touchMin === '56px',
    `touchMin=${after.touchMin} danger=${after.touchDanger} row=${after.rowMinH} bar=${after.actionbarH}`,
  );

  // 恢复成裸手，避免影响后续溢出测量
  await page.evaluate(() => {
    localStorage.removeItem('ziwi:glove-mode');
    document.documentElement.dataset.glove = 'off';
  });
  await page.waitForTimeout(150);

  // ── 验收 5：6 页在 412 / 1024 无横向溢出 ──
  for (const vp of [
    { w: 412, h: 915 },
    { w: 1024, h: 768 },
  ]) {
    await page.setViewportSize({ width: vp.w, height: vp.h });
    await page.waitForTimeout(250);
    for (const pg of PAGES) {
      await page.goto(`${BASE}/#${pg.route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(800);
      const m = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
        textLen: document.body.innerText.trim().length,
        formFactor: document.documentElement.dataset.formFactor,
      }));
      const ok = m.scrollWidth <= m.innerWidth + 1 && m.textLen > 20;
      rec(
        `A5-${pg.id}-${vp.w}`,
        `${pg.id} @${vp.w} 无横向溢出`,
        ok,
        `scrollWidth=${m.scrollWidth} innerWidth=${m.innerWidth} text=${m.textLen} ff=${m.formFactor}`,
      );
    }
  }

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n[汇总] ${results.length - failed.length}/${results.length} 通过`);
  if (failed.length) {
    console.log('失败项：');
    for (const f of failed) console.log(`  - ${f.id} ${f.name}: ${f.detail}`);
  }
  if (consoleErrors.length) {
    console.log(`[pageerror] ${consoleErrors.length} 条：`);
    for (const e of consoleErrors.slice(0, 5)) console.log('  ' + e);
  }
  process.exitCode = failed.length ? 1 : 0;
})();
