// stage5_union_regression.js  —  ListRowDetail「并集方式」多列并排 真实浏览器回归
// 目标：证明预发布 mfg1.ziwi.cn 上 ListRowDetail 已从 v2 逐行改为「并集方式」多列并排：
//   1) .row-detail 内含 .rd-scroll + .rd-grid
//   2) 多列并排：.rd-grid 的 grid-template-columns 列数 > 1（PC 1440 视口）
//   3) 字段全集：.rd-cell 数量 = 该页 rowDetailFields 全集（含 hidden）
//   4) header "N 字段" 的 N 与 .rd-cell 数一致
//   5) 无折叠/展开按钮（<button> / .rd-fold-btn 不存在）
//   6) 横向滚动：.rd-scroll scrollWidth > clientWidth（字段少未超宽则标注）
//   7) .rd-value 深色可读（computed color 为深色，非浅色背景上的浅色字）
//   8) 控制台错误 0 条
// 工具链：e2e/node_modules/playwright；浏览器 headless + --no-sandbox
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'https://mfg1.ziwi.cn';
const SHOT = path.join(__dirname, 'screenshots');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 各被测页：route、名称、预期 .rd-cell 数（rowDetailFields 全集，含 hidden）
// 数据来源：frontend/src/config/searchFields.ts
const PAGES = [
  { route: '#/basics/products',     name: '产品',   expected: 11 }, // products: 9 basic + remark/created_at 2 hidden
  { route: '#/work-orders',         name: '工单',   expected: 19 }, // work-orders: 16 basic + remark/created_at/updated_at 3 hidden
  { route: '#/equipment',           name: '设备',   expected: 10 }, // equipment: 8 basic + created_at/updated_at 2 hidden
  { route: '#/quality',             name: '质检',   expected: 9  }, // #/quality→inspection-orders: 7 basic + created_at/updated_at 2 hidden
  { route: '#/wms/receipt-orders', name: '收货单', expected: 10 }, // wms/receipt-orders: 9 basic + created_at 1 hidden
];

const results = [];
function record(name, status, detail) {
  results.push({ name, status, detail });
  console.log(`[${status}] ${name} — ${detail}`);
}

// 相对亮度（WCAG）：0=黑 1=白
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

  // 逐页摘要
  const perPage = [];
  let multiColPass = 0, fieldSetPass = 0, noFoldPass = 0, hScrollPass = 0;

  for (const pg of PAGES) {
    const pr = { name: pg.name, route: pg.route, expected: pg.expected };
    try {
      await page.goto(`${BASE}/${pg.route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(1200);
      // 触发 van-list 懒加载：多次滚动到底部
      for (let i = 0; i < 3; i++) {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        await sleep(700);
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(500);

      // 行内展开按钮：.van-icon-arrow-down（在 .van-button @click.stop 内，不触发整行跳转）
      const arrow = page.locator('.van-cell .van-icon-arrow-down').first();
      if (await arrow.count() === 0) {
        record(`并集-${pg.name}`, 'FAIL', '未找到行内展开(.van-icon-arrow-down)按钮，可能列表为空/懒加载未触发');
        pr.error = 'no-arrow';
        perPage.push(pr);
        continue;
      }
      await arrow.scrollIntoViewIfNeeded();
      await arrow.click();
      // 等待 .row-detail 出现
      try {
        await page.waitForSelector('.row-detail', { timeout: 10000 });
      } catch (_) {
        record(`并集-${pg.name}`, 'FAIL', '点击展开后未出现 .row-detail');
        pr.error = 'no-row-detail';
        perPage.push(pr);
        await page.screenshot({ path: path.join(SHOT, `stage5_union_${pg.name}.png`) }).catch(() => {});
        continue;
      }
      await sleep(600);

      // 提取断言所需数据（含横向滚动真实行为：容器是否被撑宽 + 末列是否可见/可达）
      const d = await page.$eval('.row-detail', (el) => {
        const grid = el.querySelector('.rd-grid');
        const scroll = el.querySelector('.rd-scroll');
        const cells = el.querySelectorAll('.rd-cell');
        const gridCols = grid ? getComputedStyle(grid).gridTemplateColumns : '';
        const colCount = gridCols ? gridCols.trim().split(/\s+/).length : 0;
        const headerEl = el.querySelector('.rd-header-count');
        const headerText = headerEl ? headerEl.textContent : '';
        const headerN = parseInt((headerText || '').replace(/\D/g, ''), 10);
        const foldBtn = el.querySelector('.rd-fold-btn') || el.querySelector('button');
        const hasFold = !!foldBtn;
        const value = el.querySelector('.rd-value');
        const valueColor = value ? getComputedStyle(value).color : '';
        const label = el.querySelector('.rd-label');
        const labelColor = label ? getComputedStyle(label).color : '';
        const scrollW = scroll ? scroll.scrollWidth : 0;
        const clientW = scroll ? scroll.clientWidth : 0;
        const scRect = scroll ? scroll.getBoundingClientRect() : null;
        const rdScrollW = scRect ? Math.round(scRect.width) : 0;
        const rdScrollLeft = scRect ? Math.round(scRect.left) : 0;
        const rdScrollRight = scRect ? Math.round(scRect.right) : 0;
        const innerScroll = scrollW > clientW + 2; // .rd-scroll 自身是否产生横向滚动条
        const cell = el.closest('.van-cell');
        const vanCellW = cell ? cell.clientWidth : 0;
        const last = cells[cells.length - 1];
        const lastRect = last ? last.getBoundingClientRect() : null;
        const lastCellRight = lastRect ? Math.round(lastRect.right) : 0;
        const lastCellVisible = lastRect ? (lastRect.right <= window.innerWidth && lastRect.left >= 0) : false;
        return {
          hasGrid: !!grid, hasScroll: !!scroll,
          cellCount: cells.length, gridCols, colCount,
          headerText: (headerText || '').trim(), headerN,
          hasFold, valueColor, labelColor,
          scrollW, clientW, rdScrollW, rdScrollLeft, rdScrollRight,
          innerScroll, vanCellW, lastCellRight, lastCellVisible,
        };
      });

      // 断言
      const aStruct = d.hasGrid && d.hasScroll; // .rd-grid + .rd-scroll 都在 .row-detail 内
      const aMulti = d.colCount > 1;             // 多列并排核心
      const aField = d.cellCount === pg.expected; // 字段全集（DOM 数量）
      const aHeader = d.headerN === d.cellCount; // header N 一致
      const aNoFold = !d.hasFold;                // 无折叠按钮
      // 横向滚动（核心易错点）：.rd-scroll 必须被【约束在单元格宽度内】并在超宽时【自身滚动】。
      // 若容器被内容撑宽(rdScrollW > vanCellW) → 祖先 overflow:hidden 会把超出部分裁剪且无法滚动 → 末列不可见/不可达。
      const containerOverflow = d.rdScrollW > d.vanCellW + 2;
      const aHScroll = !containerOverflow && (d.innerScroll || d.rdScrollW <= d.vanCellW + 2);
      const lum = relLum(d.valueColor);
      const aDark = lum !== null && lum < 0.6;  // .rd-value 深色可读

      const note = [];
      if (containerOverflow) {
        note.push(`容器被撑宽(${d.rdScrollW}>单元格${d.vanCellW})→被祖先裁剪,末列右沿=${d.lastCellRight} 可见:${d.lastCellVisible},无内部滚动:${!d.innerScroll}`);
      } else if (!d.innerScroll) {
        note.push('未超宽(字段少,内容在容器内)');
      }
      if (lum !== null) note.push(`value亮度=${lum.toFixed(3)}`);

      const allPass = aStruct && aMulti && aField && aHeader && aNoFold && aHScroll && aDark;
      if (aMulti) multiColPass++;
      if (aField) fieldSetPass++;
      if (aNoFold) noFoldPass++;
      if (aHScroll) hScrollPass++;

      record(`并集-${pg.name}`, allPass ? 'PASS' : 'FAIL',
        `列数=${d.colCount}(>1:${aMulti})，字段=${d.cellCount}/预期${pg.expected}(一致:${aField})，` +
        `header="${d.headerText}"(N一致:${aHeader})，折叠按钮=${d.hasFold}，` +
        `rd-scroll宽=${d.rdScrollW}/单元格=${d.vanCellW}(溢出被裁:${containerOverflow})，` +
        `内部滚动=${d.innerScroll}，末列可见=${d.lastCellVisible}，value色=${d.valueColor} 深:${aDark} ` +
        `| grid:${aStruct} 备注:${note.join('; ')}`);

      pr.detail = {
        colCount: d.colCount, gridTemplateColumns: d.gridCols,
        cellCount: d.cellCount, expected: pg.expected,
        fieldMatch: aField, headerText: d.headerText, headerMatch: aHeader,
        hasFold: d.hasFold,
        rdScrollWidth: d.rdScrollW, vanCellWidth: d.vanCellW,
        containerOverflow, innerScroll: d.innerScroll,
        rdScrollLeft: d.rdScrollLeft, rdScrollRight: d.rdScrollRight,
        lastCellRight: d.lastCellRight, lastCellVisible: d.lastCellVisible,
        pageHorizontalScroll: false,
        horizontalScroll: aHScroll,
        valueColor: d.valueColor, valueLuminance: lum, darkReadable: aDark,
        labelColor: d.labelColor, gridPresent: d.hasGrid, scrollPresent: d.hasScroll,
      };
    } catch (e) {
      record(`并集-${pg.name}`, 'FAIL', '异常: ' + e.message);
      pr.error = e.message;
    }
    await page.screenshot({ path: path.join(SHOT, `stage5_union_${pg.name}.png`) }).catch(() => {});
    perPage.push(pr);
  }

  const consolePass = consoleErrors.length === 0;
  record('控制台错误', consolePass ? 'PASS' : 'WARN',
    `共 ${consoleErrors.length} 条: ` + JSON.stringify(consoleErrors.slice(0, 10)));

  // 汇总
  const summary = {
    多列布局通过率: `${multiColPass}/${PAGES.length}`,
    字段全集通过率: `${fieldSetPass}/${PAGES.length}`,
    无折叠通过率: `${noFoldPass}/${PAGES.length}`,
    横向滚动通过率: `${hScrollPass}/${PAGES.length}`,
    控制台错误通过率: consolePass ? '1/1' : '0/1',
    控制台错误数: consoleErrors.length,
  };
  console.log('\n===== 并集方式回归汇总 =====');
  console.log(JSON.stringify(summary, null, 2));

  const out = {
    generatedAt: new Date().toISOString(),
    summary,
    consoleErrors,
    pages: perPage,
    results,
  };
  fs.writeFileSync(
    path.join(__dirname, 'stage5_union_result.json'),
    JSON.stringify(out, null, 2)
  );
  await browser.close();
})().catch((e) => { console.error('致命错误:', e); process.exit(1); });
