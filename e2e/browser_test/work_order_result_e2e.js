// work_order_result_e2e.js — 工单「结果反馈闭环」端到端验证（真实浏览器 + 真实后端）
//
// 前置：后端 :8000 + 前端 :5173 已启动，且前端产物为最新构建。
//
// 验证目标（对应 `docs/scenario-verification-2026-10-29.md` §八 未闭项）：
//   R1  建单接口回 data.id —— 建完直接进详情，不用"回列表→搜索→点进去"
//   R2  建单失败时把后端人话说出来（"工单号已存在，请换一个单号"），
//       而不是固定的"创建失败"
//   R3  完工弹窗讲清入库单：单号、仓库、数量、"待收货"状态
//   R4  弹窗能一键跳到那张入库单
//   R5  自动补建成品档案时，弹窗要点明（否则用户不知道物料页多了条档案）
//   R6  全程 0 JS 错误
//
// 用 admin（mfg_admin/admin123）跑，因为它同时有 M01 执行权与 M04 入库单读权；
// 权限门本身由 perm_button_gate_e2e.js 负责，这里不重复。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'work_order_result');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const TS = Date.now().toString().slice(-6);

const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
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
  async function bodyText() { return await page.evaluate(() => document.body.innerText); }

  async function loginAs(username, password) {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const res = await page.evaluate(async ({ username, password }) => {
      const r = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, tenant_id: 'mfg_demo' }),
      });
      const data = await r.json().catch(() => null);
      if (!r.ok) return { ok: false, status: r.status };
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token || '');
      localStorage.setItem('tenant_id', 'mfg_demo');
      const raw = await fetch('/api/v1/auth/me', {
        headers: { Authorization: 'Bearer ' + data.access_token, 'X-Tenant-Id': 'mfg_demo' },
      }).then(x => x.json());
      // /auth/me 走统一响应包装，用户信息在 data 里
      const me = raw && raw.data ? raw.data : raw;
      localStorage.setItem('user_info', JSON.stringify(me));
      return { ok: true, perms: me.permissions || [] };
    }, { username, password });
    await page.goto(`${BASE}/#/cockpit`, { waitUntil: 'networkidle', timeout: 30000 });
    // 必须硬刷新：只改 hash 不重跑 main.ts 的 auth.init()
    await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
    await sleep(900);
    return res;
  }

  async function api(method, p, body) {
    return await page.evaluate(async ({ method, url, body }) => {
      const token = localStorage.getItem('access_token');
      const tenant = localStorage.getItem('tenant_id');
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token,
          'X-Tenant-Id': tenant || '',
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      let data; try { data = await res.json(); } catch { data = null; }
      return { status: res.status, data };
    }, { method, url: `${BASE}/api/v1${p}`, body });
  }

  const dash = () => page.locator('.van-dialog:visible').first();

  // ══════════ 登录 ══════════
  const admin = await loginAs('mfg_admin', 'admin123');
  rec('R0', 'admin 登录', admin.ok ? 'PASS' : 'FAIL', `perms=${(admin.perms || []).length}`);

  // ══════════ R1 建单接口回 id ══════════
  const woNo = `WO-RES-${TS}`;
  const prodCode = `PRO-RES-${TS}`;
  const prodName = `反馈验证件${TS}`;
  const created = await api('POST', '/work-orders', {
    wo_no: woNo, product_code: prodCode, product_name: prodName, planned_qty: 12,
  });
  const newId = created.data && created.data.data && created.data.data.id;
  rec('R1', 'POST /work-orders 返回 data.id', newId ? 'PASS' : 'FAIL',
    `status=${created.status} id=${newId}`);
  if (!newId) {
    rec('R1b', '后续用例依赖 id，无法继续', 'FAIL', JSON.stringify(created.data).slice(0, 200));
    return finish();
  }

  // 后端准备：下达 + 报工（报工自动开工），让工单到"生产中"才有「完工」按钮
  const released = await api('POST', `/work-orders/${newId}/release`, {});
  const reported = await api('POST', '/work-reports', {
    work_order_id: newId, report_date: new Date().toISOString().slice(0, 10),
    output_qty: 12, labor_hours: 3, machine_hours: 1.5,
  });
  rec('R2', '前置：下达 + 报工成功', released.status === 200 && reported.status === 200 ? 'PASS' : 'FAIL',
    `release=${released.status} report=${reported.status}`);

  // ══════════ R3 完工弹窗讲清入库单 ══════════
  await page.goto(`${BASE}/#/work-orders/${newId}`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1200);
  await shot('R3_detail_before');

  const completeBtn = page.locator('button:visible', { hasText: '完工' }).first();
  const hasComplete = await completeBtn.count();
  rec('R3a', '生产中工单详情有「完工」按钮', hasComplete > 0 ? 'PASS' : 'FAIL',
    `count=${hasComplete}`);
  await completeBtn.click();
  await sleep(1500);
  await shot('R3_complete_dialog');

  const dlgText = (await dash().count()) ? await dash().innerText() : '';
  rec('R3b', '完工后弹窗出现（不再只弹一句"操作成功")', dlgText.length > 0 ? 'PASS' : 'FAIL',
    dlgText ? dlgText.replace(/\n/g, ' | ').slice(0, 160) : '没有弹窗');
  rec('R3c', '弹窗写明入库单号', /已生成生产入库单：\s*PRD-/.test(dlgText) ? 'PASS' : 'FAIL',
    (dlgText.match(/已生成生产入库单：[^\n]*/) || [''])[0]);
  rec('R3d', '弹窗写明入库仓库', /入库仓库：/.test(dlgText) ? 'PASS' : 'FAIL',
    (dlgText.match(/入库仓库：[^\n]*/) || [''])[0]);
  rec('R3e', '弹窗写明入库数量', /入库数量：/.test(dlgText) ? 'PASS' : 'FAIL',
    (dlgText.match(/入库数量：[^\n]*/) || [''])[0]);
  rec('R3f', '弹窗说明"待收货"状态（不是已入库）', /待收货/.test(dlgText) ? 'PASS' : 'FAIL',
    (dlgText.match(/状态为待收货[^\n]*/) || [''])[0]);

  // ══════════ R5 自动补建成品档案要点明 ══════════
  rec('R5', '弹窗点明成品档案已自动建立', /成品档案：已自动建立/.test(dlgText) ? 'PASS' : 'FAIL',
    (dlgText.match(/成品档案：[^\n]*/) || [''])[0]);

  // ══════════ R4 一键跳转入库单 ══════════
  const jumpBtn = page.locator('.van-dialog__confirm:visible').first();
  const jumpText = (await jumpBtn.count()) ? (await jumpBtn.innerText()).trim() : '';
  rec('R4a', '弹窗有「查看入库单」按钮', /查看入库单/.test(jumpText) ? 'PASS' : 'FAIL',
    `button=${jumpText}`);
  if (/查看入库单/.test(jumpText)) {
    await jumpBtn.click();
    await sleep(1600);
    await shot('R4_receipt_detail');
    const url = page.url();
    rec('R4b', '点击后跳到入库单详情', /#\/wms\/receipt-orders\/\d+/.test(url) ? 'PASS' : 'FAIL', url);
    const txt = await bodyText();
    rec('R4c', '入库单详情页显示出这张单', /PRD-/.test(txt) ? 'PASS' : 'FAIL',
      (txt.match(/PRD-\d{8}-\d{4}/) || [''])[0]);
  } else {
    rec('R4b', '点击后跳到入库单详情', 'FAIL', '没有跳转按钮');
    rec('R4c', '入库单详情页显示出这张单', 'FAIL', '没有跳转按钮');
  }

  // ══════════ R2 建单失败要说后端人话 ══════════
  await page.goto(`${BASE}/#/work-orders/create`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(900);
  const inputs = page.locator('input:visible');
  // 表单顺序：工单号 / 产品编码 / 产品名称 / 计划数量
  await inputs.nth(0).fill(woNo); // 故意用已存在的工单号
  await inputs.nth(1).fill(`PRO-DUP-${TS}`);
  await inputs.nth(2).fill(`重复号验证${TS}`);
  await inputs.nth(3).fill('5');
  await shot('R2_before_submit');
  await page.locator('button[type=submit]:visible').first().click();
  await sleep(1800);
  await shot('R2_duplicate_toast');
  const afterText = await bodyText();
  rec('R2a', '重复工单号时提示后端人话（不是"创建失败")',
    /已存在|请换一个单号/.test(afterText) ? 'PASS' : 'FAIL',
    (afterText.match(/[^\n]*已存在[^\n]*/) || ['(未见"已存在")'])[0].slice(0, 120));

  // ══════════ R1b 新建成功后直接进详情 ══════════
  const freshNo = `WO-RES2-${TS}`;
  await page.goto(`${BASE}/#/work-orders/create`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(900);
  const inputs2 = page.locator('input:visible');
  await inputs2.nth(0).fill(freshNo);
  await inputs2.nth(1).fill(`PRO-RES2-${TS}`);
  await inputs2.nth(2).fill(`反馈验证件2-${TS}`);
  await inputs2.nth(3).fill('8');
  await page.locator('button[type=submit]:visible').first().click();
  await sleep(2000);
  await shot('R1b_after_create');
  const url2 = page.url();
  rec('R1b', '建单成功直接跳到工单详情', /#\/work-orders\/\d+$/.test(url2) ? 'PASS' : 'FAIL', url2);
  const detailTxt = await bodyText();
  rec('R1c', '详情页显示的是刚建的那张单', detailTxt.includes(freshNo) ? 'PASS' : 'FAIL',
    freshNo);

  // ══════════ R6 无 JS 错误 ══════════
  rec('R6', '全程 0 个 JS 错误', consoleErrors.length === 0 ? 'PASS' : 'FAIL',
    consoleErrors.slice(0, 3).join(' ‖ ') || 'none');

  finish();

  function finish() {
    const pass = results.filter(r => r.status === 'PASS').length;
    const fail = results.filter(r => r.status === 'FAIL').length;
    console.log('\n' + '='.repeat(66));
    console.log(`合计 ${results.length} 项：PASS ${pass} / FAIL ${fail}`);
    if (fail) {
      console.log('失败项：');
      results.filter(r => r.status === 'FAIL').forEach(r => console.log(`  - ${r.id} ${r.name}`));
    }
    browser.close().then(() => process.exit(fail ? 1 : 0));
  }
})();
