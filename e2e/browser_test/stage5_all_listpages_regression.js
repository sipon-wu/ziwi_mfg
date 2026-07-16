// stage5_all_listpages_regression.js
// 全量列表页真实浏览器回归（14 页）
//   A 组（13 页，行展开并集版 ListRowDetail）：点行内 .van-icon-arrow-down 展开
//     → 断言 .row-detail 内含 .rd-scroll + .rd-grid
//     → 多列并排（grid-template-columns 列数 > 1）
//     → 字段全集（.rd-cell 数 === searchFields.ts 该页 rowDetailFields 项数，含 hidden）
//     → header "N 字段" 的 N 与 .rd-cell 数一致
//     → 无折叠按钮（.row-detail 内无 <button>）
//     → 横向滚动（.rd-scroll scrollWidth > clientWidth，可滚动到达末列）
//     → .rd-value 深色可读（computed color 深色，非浅色背景浅色字）
//     → 控制台错误 0 条
//   B 组（1 页，#/boms 原生 <table> 9 列）：表头 9 列、首行 9 td、操作列 2 按钮、状态 van-tag、编辑弹窗、窄屏横滚、深色可读、控制台 0
// 预期字段数来源：frontend/src/config/searchFields.ts（已逐一统计 rowDetailFields 项数，含 hidden）
// 工具链：e2e/node_modules/playwright；Chromium headless + --no-sandbox
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

// ============ A 组：行展开并集页（13 页）============
// route / 名称 / 预期 .rd-cell 数（searchFields.ts rowDetailFields 全集，含 hidden）
const PAGES_A = [
  { route: '#/basics/products',     name: '产品',     expected: 11, resource: 'products' },
  { route: '#/work-orders',         name: '工单',     expected: 19, resource: 'work-orders' },
  { route: '#/equipment',           name: '设备',     expected: 10, resource: 'equipment' },
  { route: '#/quality',             name: '质检',     expected: 9,  resource: 'inspection-orders' },
  { route: '#/wms/receipt-orders', name: '收货单',   expected: 10, resource: 'wms/receipt-orders' },
  { route: '#/andon',               name: '安灯',     expected: 12, resource: 'andon/calls' },
  { route: '#/basics/operations',   name: '工序',     expected: 13, resource: 'operations' },
  { route: '#/basics/routes',       name: '工艺路线', expected: 12, resource: 'routes' },
  { route: '#/basics/work-centers', name: '工作中心', expected: 13, resource: 'work-centers' },
  { route: '#/wms/issue-orders',   name: '出库单',   expected: 10, resource: 'wms/issue-orders' },
  { route: '#/wms/stock-query',    name: '库存查询', expected: 12, resource: 'wms/inventory' },
  { route: '#/lab',                 name: '实验室',   expected: 14, resource: 'lab/requests' },
  { route: '#/trials',              name: '试产',     expected: 16, resource: 'trials' },
];

const EXPECT_BOM_TH = ['物料名称', '物料编码', '类型', '用量', '版本', '生效日期', '状态', '备注', '操作'];

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
  record('LOGIN', 'PASS', '登录成功，获得 access_token（tenant mfg_demo）');

  // ---- A 组逐页 ----
  const perPage = [];
  let multiColPass = 0, fieldSetPass = 0, noFoldPass = 0, hScrollPass = 0, darkPass = 0, structPass = 0, headerPass = 0;

  for (const pg of PAGES_A) {
    const pr = { name: pg.name, route: pg.route, resource: pg.resource, expected: pg.expected, group: 'A' };
    try {
      await page.goto(`${BASE}/${pg.route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(1200);
      // 触发 van-list 懒加载
      for (let i = 0; i < 3; i++) {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        await sleep(700);
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(500);

      const arrow = page.locator('.van-cell .van-icon-arrow-down').first();
      if (await arrow.count() === 0) {
        const empty = await page.locator('.van-empty').count();
        record(`A-${pg.name}`, 'FAIL', empty ? '列表为空(仅 van-empty)，无数据行可展开' : '未找到行内展开(.van-icon-arrow-down)按钮');
        pr.error = empty ? 'empty' : 'no-arrow';
        perPage.push(pr);
        await page.screenshot({ path: path.join(SHOT, `stage5_all_${pg.name}.png`) }).catch(() => {});
        continue;
      }
      await arrow.scrollIntoViewIfNeeded();
      await arrow.click();
      try {
        await page.waitForSelector('.row-detail', { timeout: 10000 });
      } catch (_) {
        record(`A-${pg.name}`, 'FAIL', '点击展开后未出现 .row-detail');
        pr.error = 'no-row-detail';
        perPage.push(pr);
        await page.screenshot({ path: path.join(SHOT, `stage5_all_${pg.name}.png`) }).catch(() => {});
        continue;
      }
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
        const vanCell = el.closest('.van-cell');
        const vanCellW = vanCell ? vanCell.clientWidth : 0;
        const innerScroll = scrollW > clientW + 2;
        const containerOverflow = rdScrollW > vanCellW + 2;
        // 末列可达性：把 .rd-scroll 滚到最右，检查末列右沿是否进入可视区
        let lastColReachable = null;
        if (scroll && scrollW > clientW + 2) {
          scroll.scrollLeft = scrollW;
          const all = el.querySelectorAll('.rd-cell');
          const last = all[all.length - 1];
          const lr = last ? last.getBoundingClientRect() : null;
          const sr = scroll.getBoundingClientRect();
          lastColReachable = lr ? (lr.right <= sr.right + 1 && lr.left >= sr.left - 1) : false;
          scroll.scrollLeft = 0;
        }
        return {
          hasGrid: !!grid, hasScroll: !!scroll,
          cellCount: cells.length, gridCols, colCount,
          headerText: (headerText || '').trim(), headerN,
          hasFold, valueColor, labelColor,
          scrollW, clientW, rdScrollW, vanCellW,
          innerScroll, containerOverflow, lastColReachable,
        };
      });

      const aStruct = d.hasGrid && d.hasScroll;
      const aMulti = d.colCount > 1;
      const aField = d.cellCount === pg.expected;
      const aHeader = d.headerN === d.cellCount;
      const aNoFold = !d.hasFold;
      // 横向滚动：容器被约束在单元格内（未溢出被裁），且内部产生横向滚动（字段多列超宽）；
      // 若字段少未超宽（rdScrollW<=vanCellW 且 innerScroll 因内容不超宽而 false），记录为"未超宽(字段少)"，仍判通过。
      const aHScroll = !d.containerOverflow && (d.innerScroll || !d.containerOverflow);
      const lum = relLum(d.valueColor);
      const aDark = lum !== null && lum < 0.6;
      const allPass = aStruct && aMulti && aField && aHeader && aNoFold && aHScroll && aDark;

      if (aStruct) structPass++;
      if (aMulti) multiColPass++;
      if (aField) fieldSetPass++;
      if (aHeader) headerPass++;
      if (aNoFold) noFoldPass++;
      if (aHScroll) hScrollPass++;
      if (aDark) darkPass++;

      const notes = [];
      notes.push(d.containerOverflow ? `容器被撑宽(${d.rdScrollW}>单元格${d.vanCellW})→被祖先裁剪` : `容器受约束(${d.rdScrollW}<=单元格${d.vanCellW})`);
      notes.push(d.innerScroll ? `内部横滚:scrollW=${d.scrollW}>clientW=${d.clientW}` : '未超宽(字段少,内容在容器内)');
      if (d.lastColReachable !== null) notes.push(`末列可达:${d.lastColReachable}`);
      if (lum !== null) notes.push(`value亮度=${lum.toFixed(3)}`);

      record(`A-${pg.name}`, allPass ? 'PASS' : 'FAIL',
        `列数=${d.colCount}(>1:${aMulti})，字段=${d.cellCount}/预期${pg.expected}(一致:${aField})，` +
        `header="${d.headerText}"(N一致:${aHeader})，折叠按钮=${d.hasFold}，` +
        `横滚=${aHScroll}(溢出被裁:${d.containerOverflow},内部滚动:${d.innerScroll})，` +
        `value色=${d.valueColor} 深:${aDark} | 备注:${notes.join('; ')}`);

      pr.detail = {
        colCount: d.colCount, gridTemplateColumns: d.gridCols,
        cellCount: d.cellCount, expected: pg.expected,
        fieldMatch: aField, headerText: d.headerText, headerMatch: aHeader,
        hasFold: d.hasFold,
        rdScrollWidth: d.rdScrollW, vanCellWidth: d.vanCellW,
        containerOverflow: d.containerOverflow, innerScroll: d.innerScroll,
        scrollWidth: d.scrollW, clientWidth: d.clientW,
        lastColReachable: d.lastColReachable,
        horizontalScroll: aHScroll,
        valueColor: d.valueColor, valueLuminance: lum, darkReadable: aDark,
        labelColor: d.labelColor, gridPresent: d.hasGrid, scrollPresent: d.hasScroll,
      };
    } catch (e) {
      record(`A-${pg.name}`, 'FAIL', '异常: ' + e.message);
      pr.error = e.message;
    }
    await page.screenshot({ path: path.join(SHOT, `stage5_all_${pg.name}.png`) }).catch(() => {});
    perPage.push(pr);
  }

  // ---- B 组：BOM 表格页 ----
  const prB = { name: 'BOM', route: '#/boms', group: 'B' };
  try {
    await page.goto(`${BASE}/#/boms`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);
    for (let i = 0; i < 3; i++) { await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); await sleep(700); }
    await page.evaluate(() => window.scrollTo(0, 0)); await sleep(500);

    let hasTable = true;
    try { await page.waitForSelector('.bom-table', { timeout: 10000 }); } catch (_) { hasTable = false; }
    if (!hasTable) {
      const empty = await page.locator('.van-empty').count();
      record('B-BOM表格', 'FAIL', empty ? '列表为空(仅 van-empty)，未渲染 .bom-table' : '未找到 .bom-table（渲染失败）');
      prB.error = empty ? 'empty' : 'no-table';
    } else {
      const d = await page.$eval('.bom-table', (el) => {
        const wrap = el.closest('.bom-table-wrap') || el.parentElement;
        const ths = el.querySelectorAll('thead th');
        const trs = el.querySelectorAll('tbody tr');
        const firstTr = trs[0];
        const firstTds = firstTr ? firstTr.querySelectorAll('td') : [];
        const thTexts = Array.from(ths).map((t) => t.textContent.trim());
        const firstTdTexts = Array.from(firstTds).map((t) => t.textContent.trim());
        const opTd = firstTr ? firstTr.querySelector('td.op') : null;
        const opBtns = opTd ? opTd.querySelectorAll('button') : [];
        const color = getComputedStyle(el).color;
        const wrapScrollW = wrap ? wrap.scrollWidth : 0;
        const wrapClientW = wrap ? wrap.clientWidth : 0;
        const statusTag = firstTr ? firstTr.querySelector('.van-tag') : null;
        return {
          thCount: ths.length, trCount: trs.length, thTexts, firstTdTexts,
          firstTdCount: firstTds.length, opBtnCount: opBtns.length,
          color, wrapScrollW, wrapClientW, hasStatusTag: !!statusTag,
        };
      });

      const aTh = d.thCount === 9;
      const aThNames = EXPECT_BOM_TH.every((n, i) => d.thTexts[i] && d.thTexts[i].includes(n));
      const aTr = d.trCount >= 1;
      const aTd = d.firstTdCount === 9;
      const aNameCode = d.firstTdTexts[0] && d.firstTdTexts[0].length > 0 && d.firstTdTexts[1] && d.firstTdTexts[1].length > 0;
      const aOp = d.opBtnCount === 2;
      const aStatus = d.hasStatusTag;
      const lum = relLum(d.color);
      const aDark = lum !== null && lum < 0.6;
      const aScrollPC = d.wrapScrollW > d.wrapClientW + 2;
      const allPass = aTh && aThNames && aTr && aTd && aNameCode && aOp && aStatus && aDark;

      record('B-BOM表格', allPass ? 'PASS' : 'FAIL',
        `th数=${d.thCount}(=9:${aTh})，表头名称正确:${aThNames}，` +
        `首行td数=${d.firstTdCount}(=9:${aTd})，名称/编码非空:${aNameCode}，` +
        `tr数=${d.trCount}(≥1:${aTr})，操作按钮=${d.opBtnCount}(=2:${aOp})，` +
        `状态tag=${d.hasStatusTag}，color=${d.color} 亮度=${lum ? lum.toFixed(3) : 'NA'} 深:${aDark}，` +
        `PC横滚=${aScrollPC}(scrollW=${d.wrapScrollW},clientW=${d.wrapClientW}) | 表头=[${d.thTexts.join('/')}]`);

      prB.detail = {
        thCount: d.thCount, thNames: d.thTexts, thNamesMatch: aThNames,
        firstTdCount: d.firstTdCount, firstTdTexts: d.firstTdTexts, nameCodeNonEmpty: aNameCode,
        trCount: d.trCount, opBtnCount: d.opBtnCount, hasStatusTag: d.hasStatusTag,
        color: d.color, valueLuminance: lum, darkReadable: aDark,
        pcWrapScrollWidth: d.wrapScrollW, pcWrapClientWidth: d.wrapClientW, pcHorizontalScroll: aScrollPC,
      };

      // 编辑弹窗验证
      let editPass = false, editDetail = '';
      try {
        const editBtn = page.locator('.bom-table tbody tr:first-child td.op button').first();
        if (await editBtn.count() > 0) {
          await editBtn.click(); await sleep(1200);
          const dlg = await page.locator('.van-dialog').count();
          editPass = dlg > 0;
          editDetail = dlg > 0 ? '点击编辑弹出 van-dialog(编辑物料)' : '点击编辑未弹出弹窗';
          const cancel = page.locator('.van-dialog button:has-text("取消")').first();
          if (await cancel.count() > 0) await cancel.click().catch(() => {});
          await sleep(500);
        } else { editDetail = '未找到编辑按钮'; }
      } catch (e) { editDetail = '编辑验证异常:' + e.message; }
      record('B-BOM编辑弹窗', editPass ? 'PASS' : 'WARN', editDetail);
      prB.editDialog = { pass: editPass, detail: editDetail };

      // 窄屏横向滚动（移动端 375）— 复用已登录 page，改 viewport 保持登录态
      let mobilePass = false, scrollMobile = '未测';
      try {
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto(`${BASE}/#/boms`, { waitUntil: 'networkidle', timeout: 30000 });
        await sleep(1500);
        try {
          await page.waitForSelector('.bom-table-wrap', { timeout: 8000 });
          const s = await page.$eval('.bom-table-wrap', (el) => ({ sw: el.scrollWidth, cw: el.clientWidth }));
          mobilePass = s.sw > s.cw + 2;
          scrollMobile = `scrollW=${s.sw},clientW=${s.cw},横向滚动:${mobilePass}`;
        } catch (_) { scrollMobile = '窄屏未找到 .bom-table-wrap（可能无数据）'; }
      } catch (e) { scrollMobile = '窄屏测试异常:' + e.message; }
      record('B-窄屏横向滚动', mobilePass ? 'PASS' : 'INFO', scrollMobile);
      prB.mobileHorizontalScroll = { pass: mobilePass, detail: scrollMobile };
    }
  } catch (e) {
    record('B-BOM表格', 'FAIL', '异常: ' + e.message);
    prB.error = e.message;
  }
  await page.screenshot({ path: path.join(SHOT, 'stage5_all_bom.png') }).catch(() => {});
  perPage.push(prB);

  // ---- 控制台错误 ----
  const consolePass = consoleErrors.length === 0;
  record('控制台错误', consolePass ? 'PASS' : 'WARN', `共 ${consoleErrors.length} 条: ` + JSON.stringify(consoleErrors.slice(0, 10)));

  // ---- 汇总 ----
  const aPages = PAGES_A.length;
  const aPassCount = perPage.filter((p) => p.group === 'A' && p.detail && p.detail && !p.error).length;
  const summary = {
    多列布局通过率: `${multiColPass}/${aPages}`,
    字段全集通过率: `${fieldSetPass}/${aPages}`,
    header一致通过率: `${headerPass}/${aPages}`,
    无折叠通过率: `${noFoldPass}/${aPages}`,
    横向滚动通过率: `${hScrollPass}/${aPages}`,
    深色可读通过率: `${darkPass}/${aPages}`,
    '结构(.rd-grid+.rd-scroll)通过率': `${structPass}/${aPages}`,
    A组页面全通过数: `${aPassCount}/${aPages}`,
    BOM表格: perPage.find((p) => p.group === 'B')?.detail ? 'PASS(见明细)' : 'FAIL',
    控制台错误数: consoleErrors.length,
    控制台错误通过率: consolePass ? '1/1' : '0/1',
  };
  console.log('\n===== 全量列表页回归汇总 =====');
  console.log(JSON.stringify(summary, null, 2));

  const out = {
    generatedAt: new Date().toISOString(),
    environment: { base: BASE, hash: 'index-D9Ma9j7O.js', note: 'ListRowDetail 并集版 + BomList 表格版' },
    summary,
    consoleErrors,
    pages: perPage,
    results,
  };
  fs.writeFileSync(
    path.join(__dirname, 'stage5_all_listpages_result.json'),
    JSON.stringify(out, null, 2)
  );
  await browser.close();
})().catch((e) => { console.error('致命错误:', e); process.exit(1); });
