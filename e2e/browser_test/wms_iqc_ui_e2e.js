// wms_iqc_ui_e2e.js — 入库单明细「收货 → 送检 → 上架」真实浏览器验证
//
// 前置：后端 :8000 + 前端 :5173 已启动，产物为最新构建。
// 覆盖改造点：ReceiptOrderDetail.vue 之前**没有任何收货/上架按钮**
// （全前端 grep 不到 receipt-order-items 调用），IQC 闭环在界面上是断的。
//
// 数据带时间戳，保留不清理。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'wms_iqc_ui');
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
    // 浏览器把 4xx 响应也记成 console error（本次刻意验证的 409 拒绝就在内），
    // 这类是预期噪声，不算 JS 运行时错误
    if (/Failed to load resource/i.test(t)) return;
    consoleErrors.push(t);
  });
  page.on('pageerror', e => consoleErrors.push('[pageerror] ' + e.message));

  async function shot(id) {
    try { await page.screenshot({ path: path.join(SHOT, `${id}.png`), fullPage: false }); } catch {}
  }
  async function goto(route) {
    await page.goto(`${BASE}/#${route}`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(900);
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
  async function bodyText() { return await page.evaluate(() => document.body.innerText); }

  // ══════════ 登录 ══════════
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(800);
  const field = (label) => page.locator('.van-field', { hasText: label }).locator('input, textarea').first();
  await field('用户名').fill('mfg_admin');
  await field('密码').fill('admin123');
  await page.locator('button[type="submit"]').click();
  await sleep(2000);
  rec('W1', '登录', page.url().includes('login') ? 'FAIL' : 'PASS', page.url());

  // ══════════ 预置一张入库单（1 行，走 API 更快，UI 只验证操作按钮） ══════════
  const receiptNo = `RC-UI-${TS}`;
  const created = await api('POST', '/wms/receipt-orders', {
    receipt_no: receiptNo,
    receipt_type: 'purchase',
    source_type: 'purchase',
    warehouse_id: 1,
    items: [{ line_no: 1, material_id: 1, expected_qty: 6, unit: '根' }],
  });
  const orderId = created?.data?.data?.id;
  rec('W2', '预置入库单', orderId ? 'PASS' : 'FAIL', `HTTP ${created.status} id=${orderId}`);
  if (!orderId) { console.log(JSON.stringify(created).slice(0, 300)); }

  // ══════════ 明细页渲染 ══════════
  await goto(`/wms/receipt-orders/${orderId}`);
  await shot('W3-detail');
  let txt = await bodyText();
  rec('W3', '明细页加载', txt.includes(receiptNo) ? 'PASS' : 'FAIL', txt.slice(0, 60).replace(/\n/g, ' '));
  rec('W4', '未收货时显示「收货登记」按钮',
    (await page.locator('button', { hasText: '收货登记' }).count()) > 0 ? 'PASS' : 'FAIL',
    `buttons=${await page.locator('button', { hasText: '收货登记' }).count()}`);
  rec('W5', '未送检标记为「未送检」', txt.includes('未送检') ? 'PASS' : 'FAIL', '');
  rec('W6', '未收货时不显示「送检」',
    (await page.locator('button', { hasText: '送检' }).count()) === 0 ? 'PASS' : 'FAIL', '');

  // ══════════ 收货登记 ══════════
  await page.locator('button', { hasText: '收货登记' }).first().click();
  await sleep(700);
  await shot('W7-receive-dialog');
  const dlgVisible = (await page.locator('.van-dialog').count()) > 0;
  rec('W7', '收货弹窗弹出', dlgVisible ? 'PASS' : 'FAIL', '');
  await page.locator('.van-dialog__confirm').first().click();
  await sleep(1500);
  txt = await bodyText();
  rec('W8', '收货登记成功', txt.includes('收货登记成功') ? 'PASS' : 'FAIL',
    txt.includes('收货登记成功') ? '' : txt.slice(0, 120).replace(/\n/g, ' '));
  await shot('W8-received');

  // ══════════ 送检 ══════════
  await sleep(600);
  const sendBtn = page.locator('button', { hasText: '送检' });
  rec('W9', '收货后出现「送检」按钮',
    (await sendBtn.count()) > 0 ? 'PASS' : 'FAIL', `count=${await sendBtn.count()}`);
  if ((await sendBtn.count()) > 0) {
    await sendBtn.first().click();
    await sleep(1800);
    txt = await bodyText();
    rec('W10', '送检成功（生成 IQC 单）',
      txt.includes('已送检') || txt.includes('检验单 ID') ? 'PASS' : 'FAIL',
      txt.includes('检验单 ID') ? '页面显示检验单 ID' : txt.slice(0, 120).replace(/\n/g, ' '));
    await shot('W10-submitted');
    const b = await bodyText();
    rec('W11', '检验状态变为「待检」', b.includes('待检') ? 'PASS' : 'FAIL', '');
  } else {
    rec('W10', '送检操作', 'FAIL', '按钮未出现');
    rec('W11', '检验状态变为「待检」', 'FAIL', 'skipped');
  }

  // ══════════ 未判定 → 上架应被拒 ══════════
  await goto(`/wms/receipt-orders/${orderId}`);
  const storeBtn = page.locator('button', { hasText: '上架确认' });
  if ((await storeBtn.count()) > 0) {
    await storeBtn.first().click();
    await sleep(700);
    await shot('W12-store-dialog');
    await page.locator('.van-dialog__confirm').first().click();
    await sleep(1800);
    txt = await bodyText();
    const blocked = txt.includes('尚未判定合格') || txt.includes('IQC');
    rec('W12', '已送检未判定 → 上架被拒（前端提示后端文案）',
      blocked ? 'PASS' : 'FAIL', blocked ? '提示已展示' : txt.slice(0, 140).replace(/\n/g, ' '));
    await shot('W12-store-blocked');
  } else {
    rec('W12', '已送检未判定 → 上架被拒', 'FAIL', '上架按钮未出现');
  }

  rec('W13', '无 JS 运行时错误', consoleErrors.length === 0 ? 'PASS' : 'FAIL',
    consoleErrors.slice(0, 2).join(' | ').slice(0, 160));

  const fail = results.filter(r => r.status === 'FAIL').length;
  console.log(`\nPASS ${results.length - fail} / FAIL ${fail}`);
  fs.writeFileSync(path.join(__dirname, 'wms_iqc_ui_e2e_result.json'),
    JSON.stringify({ ts: TS, results, consoleErrors }, null, 2));
  await browser.close();
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('[FATAL]', e); process.exit(2); });
