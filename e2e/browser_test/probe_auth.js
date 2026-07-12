// probe_auth.js - 认证态诊断：用真实浏览器 UI 登录 → 提取 JWT → 在浏览器上下文内调用
// 全部 5 个已知 500 端点 + 支撑数据创建，确证 mfg1 是否仍是旧代码。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'https://mfg1.ziwi.cn';
const API = 'https://mfg1.ziwi.cn/api/v1';
const SHOT = path.join(__dirname, 'screenshots');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const TS = Date.now();
const PFX = 'E2E_BROWSER_';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const log = (...a) => console.log(...a);

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleMsgs = [];
  page.on('console', m => consoleMsgs.push(`[${m.type()}] ${m.text()}`));
  page.on('pageerror', e => consoleMsgs.push(`[pageerror] ${e.message}`));

  // ---- UI 登录 ----
  log('→ 打开登录页');
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1000);
  await page.fill('#van-field-1-input', 'test_admin');
  await page.fill('#van-field-2-input', 'test123456');
  await page.screenshot({ path: path.join(SHOT, 'p_login.png') });
  await page.click('button[type="submit"]');
  await sleep(3000);
  log('登录后 URL:', page.url());

  // ---- 提取 JWT ----
  const tokenInfo = await page.evaluate(() => {
    const scan = (store) => { const o = {}; for (let i = 0; i < store.length; i++) { const k = store.key(i); o[k] = store.getItem(k); } return o; };
    const ls = scan(localStorage); const ss = scan(sessionStorage);
    const cookie = document.cookie;
    return { ls, ss, cookie };
  });
  // 找 token
  let token = null;
  for (const v of Object.values(tokenInfo.ls)) { if (v && (v.startsWith('eyJ') || v.startsWith('JWT'))) { token = v; break; } }
  if (!token) for (const v of Object.values(tokenInfo.ss)) { if (v && (v.startsWith('eyJ') || v.startsWith('JWT'))) { token = v; break; } }
  // cookie 里可能形如 token=eyJ...
  if (!token && tokenInfo.cookie) { const m = tokenInfo.cookie.match(/(?:^|;\s*)(?:token|access_token|auth_token|jwt)=([^;]+)/i); if (m) token = m[1]; }
  log('提取到 token:', token ? `是 (前12位 ${token.slice(0,12)}…)` : '否');
  log('localStorage 键:', Object.keys(tokenInfo.ls));

  if (!token) { log('❌ 无法提取 token，终止诊断'); await browser.close(); process.exit(1); }

  // ---- 浏览器内 API 调用封装（真实浏览器请求）----
  const api = async (method, p, body) => {
    return await page.evaluate(async ({ method, url, body, token }) => {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: body ? JSON.stringify(body) : undefined
      });
      let data; try { data = await res.json(); } catch { try { data = await res.text(); } catch { data = ''; } }
      return { status: res.status, body: data };
    }, { method, url: API + p, body, token });
  };

  const R = {};
  const stamp = () => new Date().toISOString().slice(11, 19);

  // 0) 登录态自检
  R['GET /auth/me'] = await api('GET', '/auth/me');
  log(`[${stamp()}] GET /auth/me →`, R['GET /auth/me'].status);

  // 1) 创建物料 / 仓库 / 库位（支撑数据，E2E_BROWSER_ 前缀，留痕不清理）
  const mat = await api('POST', '/wms/materials', { code: `${PFX}MAT_${TS}`, name: `${PFX}测试物料`, unit: 'pcs', material_type: 'raw', pick_strategy: 'fifo' });
  R['POST /wms/materials'] = mat;
  const matId = mat.body && mat.body.data && mat.body.data.id;
  log(`[${stamp()}] POST /wms/materials →`, mat.status, 'matId=', matId);

  const wh = await api('POST', '/wms/warehouses', { code: `${PFX}WH_${TS}`, name: `${PFX}测试原料仓`, type: 'raw_material' });
  R['POST /wms/warehouses'] = wh;
  const whId = wh.body && wh.body.data && wh.body.data.id;
  log(`[${stamp()}] POST /wms/warehouses →`, wh.status, 'whId=', whId);

  const loc = await api('POST', '/wms/locations', { warehouse_id: whId, location_code: `${PFX}LOC01`, location_type: 'shelf' });
  R['POST /wms/locations'] = loc;
  const locId = loc.body && loc.body.data && loc.body.data.id;
  log(`[${stamp()}] POST /wms/locations →`, loc.status, 'locId=', locId);

  // 2) 已知 BUG-1：receipt-orders 创建（500 阻断）
  if (matId && whId) {
    const ro = await api('POST', '/wms/receipt-orders', {
      receipt_no: `${PFX}RO_${TS}`, receipt_type: 'purchase', warehouse_id: whId,
      items: [{ line_no: 1, material_id: matId, expected_qty: 100, received_qty: 100, unit: 'pcs', location_id: locId, batch_no: `${PFX}B001` }]
    });
    R['POST /wms/receipt-orders (BUG-1)'] = ro;
    log(`[${stamp()}] ★ POST /wms/receipt-orders →`, ro.status, JSON.stringify(ro.body).slice(0, 200));
  }

  // 3) 已知 BUG-2/3：issue-orders 创建（500 阻断）
  if (matId && whId) {
    const io = await api('POST', '/wms/issue-orders', {
      issue_no: `${PFX}IO_${TS}`, issue_type: 'production', warehouse_id: whId,
      items: [{ line_no: 1, material_id: matId, required_qty: 10, issued_qty: 10, unit: 'pcs', from_location_id: locId }]
    });
    R['POST /wms/issue-orders (BUG-2/3)'] = io;
    log(`[${stamp()}] ★ POST /wms/issue-orders →`, io.status, JSON.stringify(io.body).slice(0, 200));
  }

  // 4) 已知 BUG-4：stock-summary 汇总（500 阻断）
  const ss = await api('GET', '/wms/reports/stock-summary');
  R['GET /wms/reports/stock-summary (BUG-4)'] = ss;
  log(`[${stamp()}] ★ GET /wms/reports/stock-summary →`, ss.status, JSON.stringify(ss.body).slice(0, 200));

  // 5) 已知 BUG-5：work-order release（500 阻断）
  const wo = await api('POST', '/work-orders', { wo_no: `${PFX}WO_${TS}`, product_code: `${PFX}P01`, product_name: `${PFX}测试产品`, planned_qty: 50, wo_type: 'production' });
  R['POST /work-orders'] = wo;
  const woId = wo.body && wo.body.data && wo.body.data.id;
  log(`[${stamp()}] POST /work-orders →`, wo.status, 'woId=', woId);
  if (woId) {
    const rel = await api('POST', `/work-orders/${woId}/release`, { force_release: true, force_reason: 'E2E探针强制下达' });
    R['POST /work-orders/{id}/release (BUG-5)'] = rel;
    log(`[${stamp()}] ★ POST /work-orders/${woId}/release →`, rel.status, JSON.stringify(rel.body).slice(0, 200));
  }

  // 6) 关联模块可用性
  R['GET /boms'] = await api('GET', '/boms');
  R['GET /wms/inventory'] = await api('GET', '/wms/inventory');
  R['GET /wms/inventory-transactions'] = await api('GET', '/wms/inventory-transactions');
  R['GET /work-orders'] = await api('GET', '/work-orders');
  log('GET /boms →', R['GET /boms'].status, '| GET /wms/inventory →', R['GET /wms/inventory'].status, '| GET /wms/inventory-transactions →', R['GET /wms/inventory-transactions'].status);

  await page.screenshot({ path: path.join(SHOT, 'p_cockpit.png') });

  const out = { tokenExtracted: !!token, console: consoleMsgs, results: R };
  fs.writeFileSync(path.join(__dirname, 'probe_auth_result.json'), JSON.stringify(out, null, 2));

  // 汇总判定
  log('\n========== 诊断结论 ==========');
  const bugKeys = ['POST /wms/receipt-orders (BUG-1)', 'POST /wms/issue-orders (BUG-2/3)', 'GET /wms/reports/stock-summary (BUG-4)', 'POST /work-orders/{id}/release (BUG-5)'];
  let stillOld = false;
  for (const k of bugKeys) { const s = R[k] && R[k].status; if (s === 500) { stillOld = true; log(`  ❌ ${k} → 500 (旧代码)`); } else { log(`  ✅ ${k} → ${s}`); } }
  log(`\n>>> mfg1 当前${stillOld ? '仍是旧代码（5处修复未部署）' : '疑似已部署修复（无 500）'}`);

  await browser.close();
})().catch(e => { console.error('致命错误:', e); process.exit(1); });
