// material_check_ui_e2e.js — 齐套检查的**界面**链路验证（真实浏览器 + 真实后端）
//
// 前置：后端 :8000 + `node _serve_mc.js`（前端 :5181，产物 frontend/dist_mc）。
//
// 验证目标（对应台账 C-44 / 场景清单 P1-4）：
//   1. 详情页能显示齐套状态（未检查 → 缺料 → 强制放行）
//   2. 「齐套预检」能在下达前告诉车间缺哪几种料、各缺多少
//   3. 「下达」被拦时弹的是**缺料明细弹窗**，不是一句干巴巴的"下达失败"
//   4. 填原因 → 强制下发能走通，状态变已下达
//
// 造数全部走接口（自建物料/产品/BOM/收货），每次跑都独立，不依赖历史数据。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_BASE || 'http://127.0.0.1:5181';
const USER = process.env.E2E_USER || 'mfg_admin';
const PWD = process.env.E2E_PWD || 'admin123';
const TENANT = process.env.E2E_TENANT || 'AH-THR';

const SHOT = path.join(__dirname, 'screenshots', 'material_check_ui');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const TS = Date.now().toString().slice(-6);

const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
const pass = (id, name, detail) => rec(id, name, 'PASS', detail);
const fail = (id, name, detail) => rec(id, name, 'FAIL', detail);
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (/Failed to load resource/i.test(t)) return;
    consoleErrors.push(t);
  });
  page.on('pageerror', e => consoleErrors.push('[pageerror] ' + e.message));

  async function shot(id) {
    try { await page.screenshot({ path: path.join(SHOT, `${id}.png`), fullPage: false }); } catch {}
  }
  const bodyText = () => page.evaluate(() => document.body.innerText);

  /** 在页面上下文里直调接口（带登录后的 token 头），返回解析后的 data */
  async function api(method, url, body) {
    return await page.evaluate(async ({ method, url, body, TENANT }) => {
      const token = localStorage.getItem('access_token');
      const r = await fetch(`/api/v1${url}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          'X-Tenant-Id': TENANT,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let json = null;
      try { json = await r.json(); } catch (e) { json = null; }
      return { status: r.status, json };
    }, { method, url, body, TENANT });
  }

  async function login() {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const res = await page.evaluate(async ({ USER, PWD, TENANT }) => {
      const r = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: USER, password: PWD, tenant_id: TENANT }),
      });
      if (!r.ok) return { ok: false, status: r.status };
      const j = await r.json();
      localStorage.setItem('access_token', j.access_token);
      localStorage.setItem('refresh_token', j.refresh_token || '');
      localStorage.setItem('tenant_id', TENANT);
      // 登录接口只回 token，不含 roles/permissions。必须自己把 /auth/me 写进
      // user_info，否则路由守卫读到空权限 —— 表现为"登录成功但详情页 403"。
      const me = await fetch('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${j.access_token}`, 'X-Tenant-Id': TENANT },
      });
      if (me.ok) {
        const mj = await me.json();
        localStorage.setItem('user_info', JSON.stringify(mj.data ?? mj));
      }
      return { ok: true };
    }, { USER, PWD, TENANT });
    if (!res.ok) {
      fail('U0', '登录', `HTTP ${res.status}`);
      return false;
    }
    // 必须硬刷新：走 hash 跳转不会重跑 auth.init()，权限还是空的
    await page.goto(`${BASE}/#/dashboard`, { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await sleep(900);
    pass('U0', '登录成功', USER);
    return true;
  }

  if (!(await login())) {
    await browser.close();
    return;
  }

  // ══════════════ 造数 ══════════════
  const codeA = `UI-A-${TS}`, codeB = `UI-B-${TS}`, prodCode = `PRO-UI-${TS}`;
  const matIds = {};
  for (const [code, name] of [[codeA, '界面料A'], [codeB, '界面料B']]) {
    const r = await api('POST', '/wms/materials', {
      code, name, unit: '个', material_type: 'raw', pick_strategy: 'fifo' });
    if (r.status !== 200) { fail('U1', '建物料', `${code} HTTP ${r.status}`); await browser.close(); return; }
    matIds[code] = (r.json.data || {}).id;
  }
  const pr = await api('POST', '/products', {
    code: prodCode, name: `界面验证件${TS}`, unit: '件', product_type: 'finished', spec: 'UI' });
  const productId = (pr.json?.data || {}).id;
  if (!productId) { fail('U1', '建产品', `HTTP ${pr.status} ${JSON.stringify(pr.json).slice(0, 120)}`); await browser.close(); return; }

  for (const [code, qty] of [[codeA, 2], [codeB, 1]]) {
    const r = await api('POST', '/boms', {
      product_id: productId, material_code: code, material_name: code,
      qty_per_unit: qty, unit: '个', material_type: 'raw', version: 1 });
    if (r.status !== 200) { fail('U2', '建 BOM', `${code} HTTP ${r.status}`); await browser.close(); return; }
  }
  // 库存：A=100（大工单不够）、B=1000（够）
  for (const [code, qty] of [[codeA, 100], [codeB, 1000]]) {
    const ro = await api('POST', '/wms/receipt-orders', {
      receipt_no: `RC-UI-${code}-${TS}`, receipt_type: 'purchase', source_type: 'purchase',
      warehouse_id: 1,
      items: [{ line_no: 1, material_id: matIds[code], expected_qty: qty, unit: '个',
                batch_no: `B-${code}-${TS}` }],
    });
    const roId = (ro.json?.data || {}).id;
    const dt = await api('GET', `/wms/receipt-orders/${roId}`);
    const items = (dt.json?.data || {}).items || [];
    if (!items.length) { fail('U3', '入库单明细', `ro_id=${roId}`); await browser.close(); return; }
    const r = await api('POST', `/wms/receipt-order-items/${items[0].id}/receive`,
      { received_qty: qty, batch_no: `B-${code}-${TS}` });
    if (r.status !== 200) { fail('U3', '收货入账', `${code} HTTP ${r.status}`); await browser.close(); return; }
  }
  pass('U1-U3', '造数完成', `A=${codeA} B=${codeB} 产品=${prodCode}`);

  // 计划 200 件：A 需 400（有 100）→ 缺 300
  const wo = await api('POST', '/work-orders', {
    wo_no: `WO-UI-${TS}`, product_code: prodCode, product_name: `界面验证件${TS}`,
    planned_qty: 200, wo_type: 'production', remark: 'UI 齐套拦截验证' });
  const woId = (wo.json?.data || {}).id;
  if (!woId) { fail('U4', '建工单', `HTTP ${wo.status} ${JSON.stringify(wo.json).slice(0, 120)}`); await browser.close(); return; }
  pass('U4', '建大工单（必然缺料）', `id=${woId} planned=200`);

  // ══════════════ 详情页 ══════════════
  await page.goto(`${BASE}/#/work-orders/${woId}`, { waitUntil: 'domcontentloaded' });
  await sleep(900);
  let text = await bodyText();
  if (/齐套状态/.test(text) && /未检查/.test(text)) {
    pass('U5', '详情页显示齐套状态（未检查）', '');
  } else {
    fail('U5', '详情页未见齐套状态', text.slice(0, 200).replace(/\s+/g, ' '));
  }
  await shot('U5_detail_before');

  // ══════════════ 齐套预检（下达前先看缺什么） ══════════════
  const preBtn = page.locator('button', { hasText: '齐套预检' }).first();
  if (!(await preBtn.count())) {
    fail('U6', '详情页没有「齐套预检」按钮', '');
  } else {
    await preBtn.click();
    await sleep(900);
    text = await bodyText();
    const dialogOk = /齐套预检 - 缺料明细/.test(text) && /缺料 1\/2/.test(text);
    if (dialogOk) {
      pass('U6', '齐套预检弹窗列出缺料', '缺料 1/2');
    } else {
      fail('U6', '齐套预检弹窗内容不符', text.slice(0, 260).replace(/\s+/g, ' '));
    }
    await shot('U6_precheck_dialog');
    // 预检弹窗只有「关闭」，不能出现「强制下发」（否则等于绕过下达拦截）
    const forceBtn = await page.locator('.van-dialog button', { hasText: '强制下发' }).count();
    if (forceBtn === 0) pass('U6b', '预检弹窗不提供强制下发', '');
    else fail('U6b', '预检弹窗出现了强制下发按钮', `count=${forceBtn}`);
  }
  // 关掉弹窗
  const closeBtn = page.locator('.van-dialog button', { hasText: '关闭' }).first();
  if (await closeBtn.count()) await closeBtn.click();
  else await page.keyboard.press('Escape');
  await sleep(500);

  // ══════════════ 下达 → 缺料弹窗（不是一句 toast） ══════════════
  const relBtn = page.locator('button', { hasText: '下达' }).first();
  if (!(await relBtn.count())) {
    fail('U7', '详情页没有「下达」按钮', '');
  } else {
    await relBtn.click();
    await sleep(1000);
    text = await bodyText();
    const ok = /齐套检查 - 缺料明细/.test(text) && /齐套率 50/.test(text);
    if (ok) pass('U7', '缺料下达被拦 → 弹缺料明细（含齐套率）', '齐套率 50%');
    else fail('U7', '下达未被拦或弹窗内容不符', text.slice(0, 300).replace(/\s+/g, ' '));
    await shot('U7_blocked_dialog');
  }

  // ══════════════ 填原因 → 强制下发 ══════════════
  const reason = page.locator('.van-dialog textarea').first();
  if (await reason.count()) {
    await reason.fill('界面验证：急单先投产，料后补');
    const okBtn = page.locator('.van-dialog button', { hasText: '强制下发' }).first();
    if (await okBtn.count()) {
      await okBtn.click();
      await sleep(1400);
      text = await bodyText();
      const released = /已下达/.test(text) && /强制放行/.test(text);
      if (released) pass('U8', '强制下发成功，状态=已下达 / 齐套=强制放行', '');
      else fail('U8', '强制下发后状态不符', text.slice(0, 300).replace(/\s+/g, ' '));
      await shot('U8_after_force');
    } else {
      fail('U8', '弹窗里没有「强制下发」按钮', '');
    }
  } else {
    fail('U8', '弹窗里没有强制下发原因输入框', '');
  }

  // ══════════════ 控制台干净 ══════════════
  if (consoleErrors.length === 0) pass('U9', '无 JS 控制台报错', '');
  else fail('U9', 'JS 控制台报错', consoleErrors.slice(0, 3).join(' | '));

  await browser.close();

  const p = results.filter(r => r.status === 'PASS').length;
  const f = results.filter(r => r.status === 'FAIL').length;
  console.log('\n============================================================');
  console.log(`PASS ${p} / FAIL ${f}`);
  if (f) results.filter(r => r.status === 'FAIL').forEach(r => console.log(`  - ${r.id} ${r.name}：${r.detail}`));
  console.log('============================================================');
  fs.writeFileSync(path.join(SHOT, 'result.json'),
    JSON.stringify({ ran_at: new Date().toISOString(), wo_id: woId, product: prodCode, results }, null, 2));
  process.exit(f ? 1 : 0);
})();
