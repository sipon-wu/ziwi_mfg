// t04a_verify.js — T04a 验收（真实后端，无 mock）
// 前置：后端 8000（uvicorn，backend/.venv）+ 前端 5173（vite dev，代理 /api→8000）
//
// 覆盖 3 条验收：
//   A1  出库单列表点一行 → 详情页显示单号与明细行，无 404
//   A2  412×915 输一个 degraded=true 的待检单号 → 出现「适用检验项」多选；
//       勾 3 项后只渲染 3 张卡片；每项两按钮实测 ≥56×56
//   A3  提交后回执显示 QC-YYYYMMDD-NNNN + 不合格数 + 时间；判 REJ 时 extra 有「已转 NCR #id」
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 't04a');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

const DEGRADED_ORDER_NO = process.env.DEGRADED_ORDER_NO || 'QC-20261101-0285';

const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push('[pageerror] ' + e.message));

  // ── 登录 ──
  try {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
    await page.fill('input[placeholder="请输入用户名"]', 'mfg_admin');
    await page.fill('input[placeholder="请输入密码"]', 'admin123');
    await page.click('button[type="submit"]');
    await sleep(2500);
    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    rec('G0', '登录 mfg_admin', token ? 'PASS' : 'FAIL', `token=${!!token}`);
  } catch (e) {
    rec('G0', '登录 mfg_admin', 'FAIL', e.message.slice(0, 160));
  }

  // ── A1：出库单详情不 404 ──
  let issueNo = '';
  try {
    await page.goto(`${BASE}/#/wms/issue-orders`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);
    const rows = page.locator('.van-cell--clickable:visible');
    const rowCount = await rows.count();
    if (rowCount === 0) throw new Error('出库单列表 0 行，无法点击');
    issueNo = (await rows.first().innerText()).split('\n')[0].trim();
    await rows.first().click();
    await sleep(2000);

    const url = page.url();
    const detailShown = await page.locator('.iod-page').count();
    const titleText = detailShown ? await page.locator('.iod-head__title').innerText() : '';
    const codeText = detailShown
      ? await page.locator('.iod-head__no').innerText().catch(() => '')
      : '';
    const lineTitle = detailShown
      ? await page.locator('.iod-card__title').last().innerText().catch(() => '')
      : '';
    const body = await page.locator('body').innerText();
    const looks404 = /页面不存在|404|找不到页面/.test(body.split('\n').slice(0, 6).join(' '));
    const ok = /#\/wms\/issue-orders\/\d+/.test(url) && detailShown > 0 && !looks404
      && titleText.includes('出库单详情') && /明细（\d+ 行）/.test(lineTitle);
    await page.screenshot({ path: path.join(SHOT, 'A1_issue_order_detail.png'), fullPage: false });
    rec('A1', '出库单列表点一行 → 详情页', ok ? 'PASS' : 'FAIL',
      `row=${issueNo} url=${url.split('#')[1]} title=${titleText} code=${codeText.replace(/\n/g, ' ')} lines=${lineTitle} 404=${looks404}`);
  } catch (e) {
    rec('A1', '出库单列表点一行 → 详情页', 'FAIL', e.message.slice(0, 200));
  }

  // ── A2 + A3：检验执行（412×915） ──
  const page412 = await ctx.newPage();
  const consoleErrors412 = [];
  page412.on('console', (m) => { if (m.type() === 'error') consoleErrors412.push(m.text()); });
  page412.on('pageerror', (e) => consoleErrors412.push('[pageerror] ' + e.message));
  await page412.setViewportSize({ width: 412, height: 915 });

  try {
    await page412.goto(`${BASE}/#/quality/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1200);
    // 扫单入场：输入单号 → 点「开始检验」
    await page412.locator('.ziwi-scan-field input').fill(DEGRADED_ORDER_NO);
    await page412.locator('.exec-locate__go').click();
    await sleep(2500);

    const bannerText = await page412.locator('.exec-banner').innerText().catch(() => '');
    const rowCount = await page412.locator('.exec-select__row').count();
    const barText = await page412.locator('.exec-select__count').innerText().catch(() => '');
    await page412.screenshot({ path: path.join(SHOT, 'A2_step1_select_items.png'), fullPage: false });

    // 勾 3 项
    const boxes = page412.locator('.exec-select__checkbox');
    for (let i = 0; i < 3; i += 1) await boxes.nth(i).check();
    await sleep(300);
    const countAfter = await page412.locator('.exec-select__count').innerText();
    await page412.locator('.ziwi-actionbar__btn--primary').click();
    await sleep(600);

    const cardCount = await page412.locator('.exec-card').count();

    // 按钮热区实测（每项两个按钮）
    const btnSizes = [];
    for (let i = 0; i < cardCount; i += 1) {
      const card = page412.locator('.exec-card').nth(i);
      for (let j = 0; j < 2; j += 1) {
        const box = await card.locator('.exec-verdict').nth(j).boundingBox();
        btnSizes.push(box ? { w: Math.round(box.width), h: Math.round(box.height) } : null);
      }
    }
    const minW = Math.min(...btnSizes.filter(Boolean).map((b) => b.w));
    const minH = Math.min(...btnSizes.filter(Boolean).map((b) => b.h));

    // 横向溢出（412 视口）
    const overflow = await page412.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    }));

    await page412.screenshot({ path: path.join(SHOT, 'A2_step2_cards.png'), fullPage: false });

    const a2ok = bannerText.includes('未关联检验标准')
      && rowCount === 21
      && countAfter.includes('已选 3 / 21')
      && cardCount === 3
      && minW >= 56 && minH >= 56
      && overflow.scrollW <= overflow.innerW + 1;
    rec('A2', '412×915 degraded 适用项多选 → 3 张卡片 + 按钮 ≥56×56', a2ok ? 'PASS' : 'FAIL',
      `banner="${bannerText.slice(0, 40)}" 候选=${rowCount} ${countAfter} 卡片=${cardCount} 按钮最小=${minW}×${minH} scrollW=${overflow.scrollW}/innerW=${overflow.innerW}`);

    // 键盘不收起：点输入框 → 点「合格」→ 焦点仍在输入框
    let focusKept = false;
    let focusDetail = '';
    try {
      await page412.locator('.exec-card__input').first().click();
      await page412.locator('.exec-verdict--pass').first().click();
      focusDetail = await page412.evaluate(() => {
        const el = document.activeElement;
        return el ? `${el.tagName}.${el.className}` : 'null';
      });
      focusKept = focusDetail.includes('exec-card__input');
    } catch (e) {
      focusDetail = 'err:' + e.message.slice(0, 60);
    }
    rec('A2b', '点判定按钮后焦点不离开输入框（键盘不收起）', focusKept ? 'PASS' : 'FAIL', `activeElement=${focusDetail}`);

    // 录 3 项实测值 + 第 1 项判不合格（造 1 个不合格，供 REJ）
    for (let i = 0; i < cardCount; i += 1) {
      await page412.locator('.exec-card__input').nth(i).fill(String(10 + i));
    }
    await page412.locator('.exec-verdict--fail').first().click();
    await sleep(300);
    await page412.locator('.ziwi-actionbar__btn--primary').click();
    await sleep(2500);

    const judgeVisible = await page412.locator('.exec-judge').isVisible().catch(() => false);
    const judgeHint = judgeVisible ? await page412.locator('.exec-judge__hint').innerText() : '';

    // 判不合格 → 回执
    await page412.locator('.exec-judge__btn--rej').click();
    await sleep(2500);

    const receiptVisible = await page412.locator('.ziwi-receipt').isVisible().catch(() => false);
    const docNo = receiptVisible
      ? await page412.locator('.ziwi-receipt__docno-value').innerText().catch(() => '')
      : '';
    const qtys = receiptVisible
      ? (await page412.locator('.ziwi-receipt__qtys').innerText().catch(() => '')).replace(/\n/g, ' | ')
      : '';
    const timeText = receiptVisible
      ? await page412.locator('.ziwi-receipt__time').innerText().catch(() => '')
      : '';
    const extra = receiptVisible
      ? await page412.locator('.ziwi-receipt__extra').innerText().catch(() => '')
      : '';
    const ncrClickable = receiptVisible
      ? await page412.locator('.exec-ncr').count()
      : 0;

    await page412.screenshot({ path: path.join(SHOT, 'A3_receipt.png'), fullPage: false });

    const a3ok = receiptVisible
      && /^QC-\d{8}-\d{4}$/.test(docNo.trim())
      && /不合格/.test(qtys)
      && timeText.trim().length > 0
      && /已转 NCR #\d+/.test(extra)
      && ncrClickable === 1;
    rec('A3', '回执：单号 + 不合格数 + 时间 + 已转 NCR', a3ok ? 'PASS' : 'FAIL',
      `receipt=${receiptVisible} docNo="${docNo.trim()}" qtys="${qtys}" time="${timeText}" extra="${extra}" ncrBtn=${ncrClickable} judge=${judgeVisible}/${judgeHint.slice(0, 30)}`);
  } catch (e) {
    rec('A2/A3', '检验执行验收', 'FAIL', e.message.slice(0, 220));
    await page412.screenshot({ path: path.join(SHOT, 'A_fail.png'), fullPage: false }).catch(() => {});
  }

  const out = {
    at: new Date().toISOString(),
    base: BASE,
    degradedOrderNo: DEGRADED_ORDER_NO,
    results,
    consoleErrors: consoleErrors.slice(0, 10),
    consoleErrors412: consoleErrors412.slice(0, 10),
  };
  fs.writeFileSync(path.join(SHOT, 'result.json'), JSON.stringify(out, null, 2), 'utf8');
  console.log('\n=== SUMMARY ===');
  for (const r of results) console.log(`${r.status} ${r.id} ${r.name}`);
  console.log('consoleErrors(desktop)=', consoleErrors.length, ' consoleErrors(412)=', consoleErrors412.length);
  await browser.close();
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
