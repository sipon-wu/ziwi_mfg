// local_alpha_e2e.js — 本地 Alpha E2E 操作闭环（Playwright/Chromium，headless）
// 前置：后端 8000 + 前端 5173 已启动，数据已 seed。
// 覆盖：登录(A) / 工单(B) / 品质+NCR 闭环(C) / WMS(D)。逐条记录 + 截图。
// 数据带时间戳唯一值，保留不清理。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'local_alpha_e2e');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const TS = Date.now().toString().slice(-6);

const results = [];
function rec(id, name, status, detail, shot) {
  results.push({ id, name, status, detail, shot });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const field = (page, label) => page.locator('.van-field', { hasText: label }).locator('input, textarea').first();

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('[pageerror] ' + e.message));

  async function shot(id) {
    const p = path.join(SHOT, `${id}.png`);
    try { await page.screenshot({ path: p, fullPage: false }); return path.basename(p); } catch { return null; }
  }
  async function goto(route) {
    await page.goto(`${BASE}/#${route}`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(900);
  }
  // 浏览器上下文内直接调后端 API（预置数据 / 旁证）
  async function api(method, p, body) {
    return await page.evaluate(async ({ method, url, body }) => {
      const token = localStorage.getItem('access_token');
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }, body: body ? JSON.stringify(body) : undefined });
      let data; try { data = await res.json(); } catch { data = null; }
      return { status: res.status, data };
    }, { method, url: `http://127.0.0.1:5173/api/v1${p}`, body });
  }

  // ══════════ A. 认证 ══════════
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(800);

  // A2 错误密码
  await field(page, '用户名').fill('mfg_admin');
  await field(page, '密码').fill('wrong-pass');
  await page.locator('button[type="submit"]').click();
  await sleep(1500);
  const a2url = page.url();
  const a2body = await page.evaluate(() => document.body.innerText);
  rec('A2', '错误密码登录被拒', a2url.includes('login') ? 'PASS' : 'FAIL', `toast=${a2body.includes('登录失败') || a2body.includes('错误')}，url=/login`);

  // A1 正确登录
  await field(page, '密码').fill('admin123');
  await page.locator('button[type="submit"]').click();
  await sleep(3000);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  const userInfo = await page.evaluate(() => localStorage.getItem('user_info'));
  rec('A1', '正确凭据登录', token ? 'PASS' : 'FAIL', `token=${!!token}, user_info=${!!userInfo}, url=${page.url().split('#')[1] || '/'}`);
  if (!token) { console.log('登录失败，终止'); await browser.close(); process.exit(1); }

  // ══════════ B. 生产管理 ══════════
  try {
    await goto('/work-orders');
    const b1cells = await page.locator('.van-cell').count();
    rec('B1', '工单列表渲染', b1cells > 0 ? 'PASS' : 'FAIL', `cells=${b1cells}`, await shot('B1'));
  } catch (e) { rec('B1', '工单列表渲染', 'FAIL', e.message.slice(0, 100)); }

  try {
    const woNo = `WO-E2E-${TS}`;
    await goto('/work-orders/create');
    await field(page, '工单号').fill(woNo);
    await field(page, '产品编码').fill('PRO-001');
    await field(page, '产品名称').fill('精密轴承座');
    await field(page, '计划数量').fill('66');
    await page.locator('button[type="submit"]').click();
    await sleep(2500);
    const body = await page.evaluate(() => document.body.innerText);
    const ok = body.includes('创建成功') || body.includes(woNo);
    rec('B2', '新建工单', ok ? 'PASS' : 'FAIL', `url=${page.url().split('#')[1] || '/'}, 列表含${woNo}=${body.includes(woNo)}`, await shot('B2'));
  } catch (e) { rec('B2', '新建工单', 'FAIL', e.message.slice(0, 100)); }

  try {
    await goto('/work-orders');
    await page.locator('.van-cell').first().click();
    await sleep(1200);
    const body = await page.evaluate(() => document.body.innerText);
    rec('B3', '工单详情', /WO-|工单/.test(body) ? 'PASS' : 'FAIL', `url=${page.url().split('#')[1] || '/'}`, await shot('B3'));
  } catch (e) { rec('B3', '工单详情', 'FAIL', e.message.slice(0, 100)); }

  // ══════════ C. 品质 + NCR 闭环 ══════════
  try {
    await goto('/quality');
    rec('C1', '检验列表渲染', (await page.locator('.van-cell').count()) > 0 ? 'PASS' : 'FAIL', `cells=${await page.locator('.van-cell').count()}`, await shot('C1'));
  } catch (e) { rec('C1', '检验列表渲染', 'FAIL', e.message.slice(0, 100)); }

  try {
    await goto('/quality/create');
    await field(page, '备注').fill('E2E 冒烟检验');
    await page.locator('button[type="submit"]').click();
    await sleep(2500);
    const body = await page.evaluate(() => document.body.innerText);
    const ok = body.includes('创建成功') || page.url().includes('/quality');
    rec('C2', '新建检验单', ok ? 'PASS' : 'FAIL', `url=${page.url().split('#')[1] || '/'}`, await shot('C2'));
  } catch (e) { rec('C2', '新建检验单', 'FAIL', e.message.slice(0, 100)); }

  try {
    await goto('/quality');
    // 列表页第一项 .van-cell 是「待检验」汇总表头（无跳转），真正可点的是「检验单#xx」项
    await page.locator('.van-cell', { hasText: '检验单#' }).first().click();
    await sleep(1200);
    const body = await page.evaluate(() => document.body.innerText);
    rec('C3', '检验详情', body.includes('检验') ? 'PASS' : 'FAIL', `url=${page.url().split('#')[1] || '/'}`, await shot('C3'));
  } catch (e) { rec('C3', '检验详情', 'FAIL', e.message.slice(0, 100)); }

  // C4 判定入口 + REJ → 自动发起 NCR（核心闭环）
  try {
    const judgeBtns = page.locator('button', { hasText: /合格|不合格|待判定/ });
    const hasJudge = (await judgeBtns.count()) >= 3;
    rec('C4', '判定入口存在', hasJudge ? 'PASS' : 'FAIL', `判定按钮=${await judgeBtns.count()}`, await shot('C4'));
    await page.locator('button', { hasText: '不合格' }).first().click();
    await sleep(2500);
    const body = await page.evaluate(() => document.body.innerText);
    const ncrShown = body.includes('不合格评审') || body.includes('NCR');
    rec('C4b', '判定REJ自动发起NCR', ncrShown ? 'PASS' : 'FAIL', `显示NCR链接=${ncrShown}`, await shot('C4b'));
  } catch (e) { rec('C4', '判定入口', 'FAIL', e.message.slice(0, 100)); }

  try {
    await goto('/quality/ncr');
    const body = await page.evaluate(() => document.body.innerText);
    rec('C5', 'NCR 列表渲染', /NC-|不合格/.test(body) ? 'PASS' : 'FAIL', `含NCR=${/NC-/.test(body)}`, await shot('C5'));
  } catch (e) { rec('C5', 'NCR 列表渲染', 'FAIL', e.message.slice(0, 100)); }

  // C6 NCR 新建（UI）
  let ncrNo = `NC-E2E-${TS}`;
  try {
    await page.locator('button', { hasText: '新建' }).first().click();
    await sleep(800);
    await field(page, '单号').fill(ncrNo);
    await page.locator('.van-popup button', { hasText: '提交' }).click();
    await sleep(2500);
    const body = await page.evaluate(() => document.body.innerText);
    const ok = body.includes(ncrNo);
    rec('C6', 'NCR 新建', ok ? 'PASS' : 'FAIL', `列表含${ncrNo}=${ok}（预期暴露 defect_qty 空值 422）`, await shot('C6'));
  } catch (e) { rec('C6', 'NCR 新建', 'FAIL', e.message.slice(0, 100)); }
  // 无论成败，离开 ncr 页重置弹窗状态（van-popup 不响应 Escape，且同 hash goto 不重挂载）
  await goto('/dashboard');

  // 预置一个 open 状态的 NCR（node 直连后端 8000，绕过 C6 的 UI 缺陷，独立验证推进/处置/流转 UI）
  let openNo = `NC-OPEN-${TS}`;
  try {
    const pr = await fetch('http://127.0.0.1:8000/api/v1/ncr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ ncr_no: openNo, source_type: 'manual', severity: 'major' }),
    });
    const pdata = await pr.json();
    if (pr.status !== 200 || pdata.code !== 0) { openNo = null; rec('C7-pre', '预置open单', 'FAIL', `HTTP ${pr.status}, code=${pdata.code}`); }
    await goto('/quality/ncr');
  } catch (e) { openNo = null; rec('C7-pre', '预置open单', 'FAIL', e.message.slice(0, 80)); }

  // C7 开始评审
  try {
    const cell = page.locator('.van-cell', { hasText: openNo });
    const startBtn = cell.locator('button', { hasText: '开始评审' }).first();
    const ok = (await startBtn.count()) > 0;
    if (ok) { await startBtn.click(); await sleep(2000); }
    const after = await cell.innerText();
    rec('C7', 'NCR 开始评审', ok && after.includes('评审中') ? 'PASS' : 'FAIL', `状态含评审中=${after.includes('评审中')}`, await shot('C7'));
  } catch (e) { rec('C7', 'NCR 开始评审', 'FAIL', e.message.slice(0, 100)); }

  // C8 处置（返工）
  try {
    const cell = page.locator('.van-cell', { hasText: openNo });
    const disBtn = cell.locator('button', { hasText: '处置' }).first();
    const ok = (await disBtn.count()) > 0;
    if (ok) {
      await disBtn.click(); await sleep(800);
      await page.locator('.van-popup .van-tag, .van-popup button', { hasText: '返工' }).first().click();
      await page.locator('.van-popup button', { hasText: '确认处置' }).click();
      await sleep(2500);
    }
    const after = await cell.innerText();
    rec('C8', 'NCR 处置(返工)', ok && after.includes('已处置') ? 'PASS' : 'FAIL', `状态含已处置=${after.includes('已处置')}`, await shot('C8'));
    await goto('/dashboard'); await goto('/quality/ncr'); // 重置弹窗/刷新列表，供 C8b 定位
  } catch (e) { rec('C8', 'NCR 处置(返工)', 'FAIL', e.message.slice(0, 100)); }

  // C8b 流转记录
  try {
    const cell = page.locator('.van-cell', { hasText: openNo });
    const trailBtn = cell.locator('button', { hasText: '流转记录' }).first();
    if ((await trailBtn.count()) > 0) {
      await trailBtn.click(); await sleep(1500);
      const body = await page.evaluate(() => document.body.innerText);
      rec('C8b', 'NCR 流转记录', body.includes('流转记录') ? 'PASS' : 'FAIL', `含流转记录=${body.includes('流转记录')}`, await shot('C8b'));
    } else { rec('C8b', 'NCR 流转记录', 'FAIL', '未找到流转记录按钮'); }
  } catch (e) { rec('C8b', 'NCR 流转记录', 'FAIL', e.message.slice(0, 100)); }

  // ══════════ D. WMS ══════════
  try { await goto('/wms/materials'); const b = await page.evaluate(() => document.body.innerText); rec('D1', '物料主数据', /45#|轴承|M-0/.test(b) ? 'PASS' : 'FAIL', `含物料=${/45#|轴承/.test(b)}`, await shot('D1')); } catch (e) { rec('D1', '物料主数据', 'FAIL', e.message.slice(0, 100)); }
  try { await goto('/wms/warehouse-tree'); const b = await page.evaluate(() => document.body.innerText); rec('D2', '仓库结构', /仓库|WH-|原料/.test(b) ? 'PASS' : 'FAIL', `含仓库=${/仓库|原料/.test(b)}`, await shot('D2')); } catch (e) { rec('D2', '仓库结构', 'FAIL', e.message.slice(0, 100)); }
  try { await goto('/wms/stock-query'); const b = await page.evaluate(() => document.body.innerText); rec('D3', '库存查询', b.length > 20 ? 'PASS' : 'FAIL', `body=${b.length}字`, await shot('D3')); } catch (e) { rec('D3', '库存查询', 'FAIL', e.message.slice(0, 100)); }

  // ══════════ 汇总 ══════════
  const pass = results.filter(r => r.status === 'PASS').length;
  const fail = results.filter(r => r.status.startsWith('FAIL')).length;
  console.log(`\n════════ 汇总 ════════`);
  console.log(`PASS ${pass} / FAIL ${fail}，控制台错误 ${consoleErrors.length}`);
  if (consoleErrors.length) console.log('  ' + consoleErrors.slice(0, 8).join('\n  '));

  fs.writeFileSync(path.join(__dirname, 'local_alpha_e2e_result.json'), JSON.stringify({ ts: new Date().toISOString(), results, consoleErrors }, null, 2));
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
