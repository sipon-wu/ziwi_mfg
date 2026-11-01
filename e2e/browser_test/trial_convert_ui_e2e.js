// trial_convert_ui_e2e.js — 试产详情页「一键转量产」真实浏览器验证
//
// 前置：后端 :8000 + 前端 :5173 已启动，产物为最新构建。
// 覆盖改造点：转产以前只翻状态位，前端也只 toast 一句「转量产成功」，
// 用户拿到的是"成功"但 BOM / 工艺路线页查不到任何东西。
// 现在要求：转产真的落库，且把"写了多少行、哪些没写、路线还是 draft"回报到界面。
//
// 数据带时间戳，保留不清理。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'trial_convert_ui');
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
  rec('U1', '登录', page.url().includes('login') ? 'FAIL' : 'PASS', page.url());
  if (page.url().includes('login')) return finish();

  // ══════════ 预置数据（走 API 更快，UI 只验证转产动作） ══════════
  const pcode = `PRO-UI-${TS}`;
  let r = await api('POST', '/products', {
    code: pcode, name: `UI转产验证件${TS}`, unit: '件', product_type: 'finished',
  });
  const productId = r.data?.data?.id ?? r.data?.id;
  rec('U2', '建产品', productId ? 'PASS' : 'FAIL', `status=${r.status} id=${productId}`);

  r = await api('POST', '/trials', {
    trial_type: 'new_product', product_id: productId,
    product_name: `UI转产验证件${TS}`, planned_qty: 60,
  });
  const orderId = r.data?.data?.id ?? r.data?.id;
  const orderNo = r.data?.data?.order_no ?? r.data?.order_no;
  rec('U3', '建试产工单', orderId ? 'PASS' : 'FAIL', `order_no=${orderNo}`);

  r = await api('PUT', `/trials/${orderId}/bom`, {
    bom_json: [
      { material_code: 'M-001', material_name: '冷轧钢板', qty_per_unit: 3, unit: 'kg' },
      { material_code: 'M-002', material_name: '深沟球轴承', qty_per_unit: 2, unit: '件' },
      { material_name: '缺编码辅料', qty_per_unit: 1, unit: 'kg' },
    ],
    source_type: 'manual',
  });
  rec('U4', '保存试产 BOM', r.status === 200 ? 'PASS' : 'FAIL', `status=${r.status}`);

  r = await api('PUT', `/trials/${orderId}/routes`, {
    route_json: [
      { operation_id: 2, step_name: '粗车外圆', step_seq: 10 },
      { operation_id: 3, step_name: '精车外圆', step_seq: 20 },
      { step_name: '缺工序主数据', step_seq: 30 },
    ],
    source_type: 'manual',
  });
  rec('U5', '保存试产路线', r.status === 200 ? 'PASS' : 'FAIL', `status=${r.status}`);

  r = await api('POST', `/trials/${orderId}/review`, { review_stage: 'final' });
  const reviewId = r.data?.data?.id ?? r.data?.id;
  rec('U6', '提交评审', reviewId ? 'PASS' : 'FAIL', `review_id=${reviewId}`);
  r = await api('POST', `/trials/${orderId}/reviews/${reviewId}/decide`, { conclusion: 'approved' });
  rec('U7', '评审通过', r.status === 200 ? 'PASS' : 'FAIL', `status=${r.status}`);

  // ══════════ U8 列表页能看到该单，且是评审阶段 ══════════
  await page.goto(`${BASE}/#/trials`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1200);
  const listTxt = await bodyText();
  rec('U8', '列表页显示新试产单', listTxt.includes(orderNo) ? 'PASS' : 'FAIL',
    listTxt.includes(orderNo) ? orderNo : '未找到行');
  await shot('U8_list');

  // ══════════ U9 进详情页 ══════════
  await page.goto(`${BASE}/#/trials/${orderId}`, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(1200);
  let txt = await bodyText();
  rec('U9', '详情页展示工单号', txt.includes(orderNo) ? 'PASS' : 'FAIL', orderNo);
  const convertBtn = page.locator('button', { hasText: '一键转量产' }).first();
  rec('U10', '评审阶段显示「一键转量产」按钮',
    (await convertBtn.count()) > 0 ? 'PASS' : 'FAIL', `count=${await convertBtn.count()}`);
  await shot('U10_detail');

  // ══════════ U11 点转产 → 确认 → 落库结果弹窗 ══════════
  if ((await convertBtn.count()) > 0) {
    await convertBtn.click();
    await sleep(700);
    const confirm = page.locator('.van-dialog__confirm, button:has-text("确认"), button:has-text("确定")').first();
    rec('U11', '弹出二次确认', (await confirm.count()) > 0 ? 'PASS' : 'FAIL',
      (await bodyText()).includes('生成正式 BOM') ? '提示含落库说明' : '提示文案异常');
    await shot('U11_confirm');
    if ((await confirm.count()) > 0) {
      await confirm.click();
      await sleep(2500);
      txt = await bodyText();
      const hasDialog = txt.includes('转量产完成');
      rec('U12', '展示「转量产完成」结果弹窗', hasDialog ? 'PASS' : 'FAIL',
        hasDialog ? '已弹出' : txt.slice(0, 120));
      rec('U13', '弹窗回报 BOM 写入行数', /正式 BOM：写入 \d+ 行/.test(txt) ? 'PASS' : 'FAIL',
        (txt.match(/正式 BOM：[^\n]*/) || [''])[0]);
      rec('U14', '弹窗回报工艺路线与 draft 状态',
        /工艺路线：\S+ 共 \d+ 道工序，状态 draft/.test(txt) ? 'PASS' : 'FAIL',
        (txt.match(/工艺路线：[^\n]*/) || [''])[0]);
      rec('U15', '弹窗列出未落库的告警',
        txt.includes('需要注意') && txt.includes('material_code') ? 'PASS' : 'FAIL',
        txt.includes('需要注意') ? '含告警清单' : '缺告警区');
      await shot('U12_result');
      // 关掉弹窗
      const ok = page.locator('.van-dialog__confirm').first();
      if ((await ok.count()) > 0) { try { await ok.click(); } catch {} await sleep(600); }
    }
  }

  // ══════════ U16 界面之外的硬证据：BOM / 路线接口真有数据 ══════════
  r = await api('GET', `/boms?product_id=${productId}&page_size=50`);
  const bomItems = r.data?.data?.items || [];
  rec('U16', 'BOM 接口查到刚生成的 2 行',
    bomItems.length === 2 ? 'PASS' : 'FAIL', `count=${bomItems.length}`);

  r = await api('GET', `/routes?keyword=RTE-${pcode}&page_size=20`);
  const routes = r.data?.data?.items || [];
  const target = routes.find(x => x.code === `RTE-${pcode}`);
  rec('U17', '工艺路线接口查到 draft 路线',
    target && target.status === 'draft' ? 'PASS' : 'FAIL',
    target ? `${target.code} status=${target.status}` : `routes=${routes.map(x => x.code)}`);
  if (target) {
    r = await api('GET', `/routes/${target.id}/steps`);
    const steps = r.data?.data || [];
    rec('U18', '路线工序 2 道且关联主数据', steps.length === 2 ? 'PASS' : 'FAIL',
      `count=${steps.length} ops=${steps.map(s => s.operation_id)}`);
  }

  // ══════════ U19 状态已翻成 production，按钮应消失 ══════════
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(1500);
  txt = await bodyText();
  const stillHasBtn = (await page.locator('button', { hasText: '一键转量产' }).count()) > 0;
  rec('U19', '转产后状态翻为已转量产且按钮消失',
    !stillHasBtn && txt.includes('转量产') ? 'PASS' : 'FAIL',
    `btn=${stillHasBtn}`);
  await shot('U19_after');

  rec('U20', '无 JS 运行时错误', consoleErrors.length === 0 ? 'PASS' : 'FAIL',
    consoleErrors.slice(0, 3).join(' | ') || '0 error');

  finish();

  function finish() {
    const pass = results.filter(x => x.status === 'PASS').length;
    const fail = results.filter(x => x.status === 'FAIL').length;
    console.log(`\n===== 合计 ${results.length} 项：PASS ${pass} / FAIL ${fail} =====`);
    if (fail) {
      console.log('失败项：');
      results.filter(x => x.status === 'FAIL').forEach(x => console.log(`  - ${x.id} ${x.name}: ${x.detail}`));
    }
    browser.close().then(() => process.exit(fail ? 1 : 0));
  }
})();
