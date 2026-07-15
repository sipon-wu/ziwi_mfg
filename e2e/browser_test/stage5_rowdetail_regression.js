// stage5_rowdetail_regression.js  (v3 — 修正测试集与高级检索关闭断言)
// 阶段⑤浏览器回归：验证 ListRowDetail v2（行展开"外层逐行"布局）在预发布 mfg1.ziwi.cn 多列表页真实表现。
// 工具链：本地 e2e/node_modules/playwright，浏览器需 --no-sandbox。
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'https://mfg1.ziwi.cn';
const SHOT = path.join(__dirname, 'screenshots');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function record(name, status, detail) {
  results.push({ name, status, detail });
  console.log(`[${status}] ${name} — ${detail}`);
}

async function uiLogin(page, user, pass) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1000);
  await page.fill('#van-field-1-input', user);
  await page.fill('#van-field-2-input', pass);
  await page.click('button[type="submit"]');
  await sleep(3000);
  return await page.evaluate(() => localStorage.getItem('access_token'));
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push('[pageerror] ' + e.message));

  // ---- 登录 ----
  let token = await uiLogin(page, 'mfg_admin', 'admin123');
  if (!token) token = await uiLogin(page, 'test_admin', 'test123456');
  if (!token) {
    record('LOGIN', 'FAIL', 'mfg_admin / test_admin 均无法登录');
    await browser.close();
    process.exit(1);
  }
  record('LOGIN', 'PASS', '登录成功，获得 access_token');

  // 确认接了 ListRowDetail 的列表页（覆盖多模块）
  const listRoutes = [
    { route: '#/basics/products', name: '产品' },
    { route: '#/work-orders', name: '工单' },
    { route: '#/equipment', name: '设备' },
    { route: '#/quality', name: '质检' },
    { route: '#/wms/receipt-orders', name: '收货单' },
  ];

  let rowExpandPass = 0, rowExpandTotal = 0;
  let advSearchPass = 0, advSearchTotal = 0;

  for (const lr of listRoutes) {
    // ===================== 行展开（外层逐行布局） =====================
    try {
      await page.goto(`${BASE}/${lr.route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(1200);
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await sleep(800);

      const expandBtn = page.locator('.van-cell .van-button:has(.van-icon-arrow-down)').first();
      if (await expandBtn.count() === 0) {
        rowExpandTotal++;
        record(`行展开-${lr.name}`, 'FAIL', '未找到行内展开(arrow-down)按钮');
      } else {
        await expandBtn.click();
        await sleep(800);
        const detail = await page.$('.row-detail');
        if (!detail) {
          rowExpandTotal++;
          record(`行展开-${lr.name}`, 'FAIL', '点击展开后未出现 .row-detail');
        } else {
          const rows = await page.$$('.row-detail .rd-row');
          const countText = await page.$eval('.rd-header-count', (el) => el.textContent).catch(() => '');
          const countNum = parseInt((countText || '').replace(/\D/g, ''), 10);
          const headerOk = countNum === rows.length;
          const foldBtn = await page.$('.row-detail .rd-fold-btn');
          const hasFold = !!foldBtn;
          let truncated = false;
          for (const r of rows) {
            const v = await r.$('.rd-value');
            if (v) {
              const clamped = await v.evaluate((el) => {
                const cs = getComputedStyle(el);
                return cs.webkitLineClamp && cs.webkitLineClamp !== 'none' && el.scrollHeight > el.clientHeight + 2;
              });
              if (clamped) truncated = true;
            }
          }
          const labels = await page.$$('.rd-row .rd-label');
          const values = await page.$$('.rd-row .rd-value');
          const ok = rows.length > 0 && labels.length === rows.length && values.length === rows.length && !hasFold && !truncated && headerOk;
          rowExpandTotal++;
          if (ok) rowExpandPass++;
          record(`行展开-${lr.name}`, ok ? 'PASS' : 'FAIL',
            `可见行 ${rows.length}，header计数=${countNum}(一致:${headerOk})，label/value配对 ${labels.length}/${values.length}，折叠按钮=${hasFold}，截断=${truncated}`);
          await page.screenshot({ path: path.join(SHOT, `stage5_row_${lr.name}.png`) });
        }
      }
    } catch (e) {
      rowExpandTotal++;
      record(`行展开-${lr.name}`, 'FAIL', '异常: ' + e.message);
    }

    // ===================== 高级检索（AdvancedSearchPanel，本任务未改动，仅做回归冒烟） =====================
    try {
      const openBtn = page.locator('text=高级检索').first();
      if (await openBtn.count() === 0) {
        advSearchTotal++;
        record(`高级检索-${lr.name}`, 'FAIL', '未找到"高级检索"按钮');
      } else {
        await openBtn.click();
        await sleep(800);
        const titleEl = await page.$('.asp-title');
        const titleText = titleEl ? await titleEl.textContent() : '';
        const titleOk = !!(titleText && titleText.includes('高级检索'));

        const addBtn = page.locator('text=+ 添加条件').first();
        let condOk = false;
        if (await addBtn.count()) {
          await addBtn.click();
          await sleep(500);
          const idx = await page.$('.asp-idx');
          const idxText = idx ? await idx.textContent() : '';
          condOk = !!(idxText && idxText.includes('条件 1'));
        }

        const inputs = await page.$$('.asp-row .van-field__control');
        if (inputs.length) {
          try { await inputs[inputs.length - 1].fill('测试'); } catch (_) { /* ignore */ }
        }

        // 修正：点击"查询"后等退场动画，再判断 .asp-title 是否仍【可见】
        const searchBtn = page.locator('button.van-button--primary:has-text("查询")').first();
        let searchOk = false;
        if (await searchBtn.count()) {
          await searchBtn.click();
          await sleep(700);
          const titleLoc = page.locator('.asp-title').first();
          const visible = await titleLoc.isVisible().catch(() => false);
          searchOk = !visible;
        }

        const ok = titleOk && condOk && searchOk;
        advSearchTotal++;
        if (ok) advSearchPass++;
        record(`高级检索-${lr.name}`, ok ? 'PASS' : 'FAIL',
          `标题=${titleOk}，添加条件=${condOk}，查询关闭弹层=${searchOk}`);
        await page.screenshot({ path: path.join(SHOT, `stage5_adv_${lr.name}.png`) });
      }
    } catch (e) {
      advSearchTotal++;
      record(`高级检索-${lr.name}`, 'FAIL', '异常: ' + e.message);
    }
  }

  record('控制台错误', consoleErrors.length === 0 ? 'PASS' : 'WARN',
    `共 ${consoleErrors.length} 条: ` + JSON.stringify(consoleErrors.slice(0, 10)));

  console.log('\n===== 阶段⑤回归汇总 =====');
  console.log(`行展开: ${rowExpandPass}/${rowExpandTotal}`);
  console.log(`高级检索: ${advSearchPass}/${advSearchTotal}`);
  console.log(`控制台错误: ${consoleErrors.length}`);
  fs.writeFileSync(
    path.join(__dirname, 'stage5_regression_result.json'),
    JSON.stringify({ rowExpand: `${rowExpandPass}/${rowExpandTotal}`, advSearch: `${advSearchPass}/${advSearchTotal}`, consoleErrors: consoleErrors.length, results }, null, 2)
  );
  await browser.close();
})().catch((e) => { console.error('致命错误:', e); process.exit(1); });
