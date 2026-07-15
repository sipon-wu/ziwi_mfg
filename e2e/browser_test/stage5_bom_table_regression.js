// stage5_bom_table_regression.js — BOM管理列表「卡片式→表格多列」真实浏览器回归
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

  let token = await uiLogin(page, 'mfg_admin', 'admin123');
  if (!token) { record('LOGIN', 'FAIL', 'mfg_admin 登录失败'); await browser.close(); process.exit(1); }
  record('LOGIN', 'PASS', '登录成功，获得 access_token');

  await page.goto(`${BASE}/#/boms`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1500);
  for (let i = 0; i < 3; i++) { await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); await sleep(700); }
  await page.evaluate(() => window.scrollTo(0, 0)); await sleep(500);

  let hasTable = true;
  try { await page.waitForSelector('.bom-table', { timeout: 10000 }); } catch (_) { hasTable = false; }
  if (!hasTable) {
    const empty = await page.locator('.van-empty').count();
    record('BOM表格', 'FAIL', empty ? '列表为空(仅 van-empty)，未渲染 .bom-table' : '未找到 .bom-table（渲染失败）');
    await page.screenshot({ path: path.join(SHOT, 'stage5_bom_table.png') }).catch(() => {});
    const out = { generatedAt: new Date().toISOString(), summary: {}, consoleErrors, results };
    fs.writeFileSync(path.join(__dirname, 'stage5_bom_table_result.json'), JSON.stringify(out, null, 2));
    await browser.close(); process.exit(0);
  }

  const d = await page.$eval('.bom-table', (el) => {
    const wrap = el.closest('.bom-table-wrap') || el.parentElement;
    const ths = el.querySelectorAll('thead th');
    const trs = el.querySelectorAll('tbody tr');
    const firstTr = trs[0];
    const firstTds = firstTr ? firstTr.querySelectorAll('td') : [];
    const thTexts = Array.from(ths).map((t) => t.textContent.trim());
    const opTd = firstTr ? firstTr.querySelector('td.op') : null;
    const opBtns = opTd ? opTd.querySelectorAll('button') : [];
    const color = getComputedStyle(el).color;
    const wrapScrollW = wrap ? wrap.scrollWidth : 0;
    const wrapClientW = wrap ? wrap.clientWidth : 0;
    const statusTag = firstTr ? firstTr.querySelector('.van-tag') : null;
    return {
      thCount: ths.length, trCount: trs.length, thTexts,
      firstTdCount: firstTds.length,
      opBtnCount: opBtns.length, color, wrapScrollW, wrapClientW,
      hasStatusTag: !!statusTag,
    };
  });

  const EXPECT_TH = ['物料名称', '物料编码', '类型', '用量', '版本', '生效日期', '状态', '备注', '操作'];
  const aTh = d.thCount === 9;
  const aThNames = EXPECT_TH.every((n, i) => d.thTexts[i] && d.thTexts[i].includes(n));
  const aTr = d.trCount >= 1;
  const aTd = d.firstTdCount === 9;
  const aOp = d.opBtnCount === 2;
  const aStatus = d.hasStatusTag;
  const lum = relLum(d.color);
  const aDark = lum !== null && lum < 0.6;
  const aScroll = d.wrapScrollW > d.wrapClientW + 2;

  const allPass = aTh && aThNames && aTr && aTd && aOp && aDark;
  record('BOM表格', allPass ? 'PASS' : 'FAIL',
    `th数=${d.thCount}(=9:${aTh})，表头名称正确:${aThNames}，` +
    `首行td数=${d.firstTdCount}(=9:${aTd})，tr数=${d.trCount}(≥1:${aTr})，` +
    `操作按钮=${d.opBtnCount}(=2:${aOp})，状态tag=${d.hasStatusTag}，` +
    `color=${d.color} 亮度=${lum ? lum.toFixed(3) : 'NA'} 深:${aDark}，` +
    `PC横滚=${aScroll}(scrollW=${d.wrapScrollW},clientW=${d.wrapClientW}) | 表头=[${d.thTexts.join('/')}]`);

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
  record('BOM编辑弹窗', editPass ? 'PASS' : 'WARN', editDetail);

  // 窄屏横向滚动（移动端 375）— 复用已登录 page，改 viewport 保持登录态
  let scrollMobile = '未测';
  let mobilePass = false;
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
  record('窄屏横向滚动', mobilePass ? 'PASS' : 'INFO', scrollMobile);

  const consolePass = consoleErrors.length === 0;
  record('控制台错误', consolePass ? 'PASS' : 'WARN', `共 ${consoleErrors.length} 条: ${JSON.stringify(consoleErrors.slice(0, 5))}`);

  const summary = {
    表头9列: aTh ? 'PASS' : 'FAIL', 表头名称正确: aThNames ? 'PASS' : 'FAIL',
    首行9td: aTd ? 'PASS' : 'FAIL', 数据行存在: aTr ? 'PASS' : 'FAIL',
    操作按钮2个: aOp ? 'PASS' : 'FAIL', 状态tag: aStatus ? 'PASS' : 'FAIL',
    深色可读: aDark ? 'PASS' : 'FAIL', 编辑弹窗: editPass ? 'PASS' : 'WARN',
    窄屏横向滚动: mobilePass ? 'PASS' : 'INFO', 控制台错误: consolePass ? 'PASS' : 'WARN',
  };
  console.log('\n===== BOM表格回归汇总 =====');
  console.log(JSON.stringify(summary, null, 2));

  await page.screenshot({ path: path.join(SHOT, 'stage5_bom_table.png') }).catch(() => {});
  const out = { generatedAt: new Date().toISOString(), summary, consoleErrors, detail: d, results };
  fs.writeFileSync(path.join(__dirname, 'stage5_bom_table_result.json'), JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error('致命错误:', e); process.exit(1); });
