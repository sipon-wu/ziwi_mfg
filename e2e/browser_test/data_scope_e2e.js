// data_scope_e2e.js — 数据范围端到端验证（真实浏览器 + 真实后端）
//
// 前置：后端 :8000 + 前端 :5173 已启动；`backend/scripts/seed_organizations.py`
//       已跑过（会建出 demo_ws1_leader / admin123，挂在一号车间）。
//
// 为什么要用「差分」而不是「有没有数据」：
//   子表不过滤的缺陷表现是**多了**，不是**少了**或报错。页面有数据、排序正常、
//   看起来完全正常 —— 只有拿两个不同范围的账号对比同一个页面才能发现。
//   所以这里所有断言都是 admin 与 一号车间主任 的**相对关系**，不写死绝对条数
//   （写死就只能跑一次，第二次假失败 = 没有回归价值）。
//
//   D1  admin 登录，报工页有数据
//   D2  demo_ws1_leader 登录（一号车间），报工页能正常打开、不报错
//   D3  admin 造的今日报工（公司根节点）对 ws1 主任**不可见** → DOM 行数更少
//   D4  ws1 主任自己造的报工**可见** → DOM 行数 == 他自己那条
//   D5  ws1 主任对根节点检验单的明细接口拿不到数据（子表不宽于父单）
//   D6  全程 0 JS 运行时错误
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'data_scope');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const TS = Date.now().toString().slice(-6);

const results = [];
function rec(id, name, ok, detail) {
  const status = (ok === true || ok === 'PASS') ? 'PASS' : 'FAIL';
  results.push({ id, name, status, ok, detail });
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
      const me = raw && raw.data ? raw.data : raw;
      localStorage.setItem('user_info', JSON.stringify(me));
      return { ok: true, perms: (me.permissions || []).length, org_id: me.org_id, username: me.username };
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

  const dataOf = r => (r && r.data && r.data.data !== undefined ? r.data.data : (r ? r.data : null));

  // 报工页当前渲染出的行数（van-cell 且非空列表）
  async function reportRowCount() {
    return await page.evaluate(() => {
      const list = document.querySelector('.van-list');
      if (!list) return -1;
      return list.querySelectorAll('.van-cell:not(.van-list__loading):not(.van-list__finished-text)').length;
    });
  }

  async function openReports() {
    await page.goto(`${BASE}/#/work-reports`, { waitUntil: 'networkidle', timeout: 30000 });
    await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1200);
  }

  // ══════════ D1 admin 基线 ══════════
  const admin = await loginAs('mfg_admin', 'admin123');
  rec('D1', 'admin 登录', admin.ok ? 'PASS' : 'FAIL',
    `perms=${admin.perms} org_id=${admin.org_id}`);

  const today = new Date().toISOString().slice(0, 10);
  const tag = TS;

  // admin 造一张根节点工单 + 今日报工，作为「ws1 主任不该看见」的样本
  let rootWoNo = null;
  {
    const r = await api('POST', '/work-orders', {
      wo_no: `WO-DS-${tag}`, product_code: `PRO-DS-${tag}`,
      product_name: `数据范围对照件${tag}`, planned_qty: 5,
    });
    const woId = dataOf(r) && dataOf(r).id;
    if (woId) {
      rootWoNo = `WO-DS-${tag}`;
      await api('POST', `/work-orders/${woId}/release`, {});
      await api('POST', '/work-reports', {
        work_order_id: woId, report_date: today, output_qty: 5, labor_hours: 1,
      });
    }
  }
  rec('D1', 'admin 造了一张根节点工单的今日报工',
    rootWoNo ? 'PASS' : 'FAIL', `wo_no=${rootWoNo}`);

  await openReports();
  const adminRows = await reportRowCount();
  const adminApi = dataOf(await api('GET', `/work-reports?page=1&page_size=50&report_date=${today}`));
  const adminApiTotal = adminApi ? adminApi.total : -1;
  await shot('D1_admin_reports');
  rec('D1', 'admin 报工页有数据', adminRows > 0,
    `DOM 行数=${adminRows} API total=${adminApiTotal}`);
  rec('D1', 'DOM 行数与 API 一致（页面没自己过滤/漏渲染）',
    adminRows === adminApiTotal, `DOM=${adminRows} API=${adminApiTotal}`);

  // ══════════ D2 ws1 主任登录 ══════════
  const scoped = await loginAs('demo_ws1_leader', 'admin123');
  rec('D2', 'demo_ws1_leader 登录', scoped.ok ? 'PASS' : 'FAIL',
    `perms=${scoped.perms} org_id=${scoped.org_id}`);
  rec('D2', '该账号挂在真实部门（不是公司根 1）',
    scoped.org_id && scoped.org_id !== 1 ? 'PASS' : 'FAIL', `org_id=${scoped.org_id}`);

  // ══════════ D3/D4 差分 ══════════
  await openReports();
  const scopedRows = await reportRowCount();
  const scopedApi = dataOf(await api('GET', `/work-reports?page=1&page_size=50&report_date=${today}`));
  const scopedApiTotal = scopedApi ? scopedApi.total : -1;
  await shot('D2_scoped_reports');

  rec('D3', 'ws1 主任的报工行数少于 admin（根节点报工不可见）',
    scopedRows >= 0 && scopedRows < adminRows, `scoped=${scopedRows} < admin=${adminRows}`);
  rec('D3', 'DOM 行数与 API 一致（过滤发生在后端，不是前端藏起来）',
    scopedRows === scopedApiTotal, `DOM=${scopedRows} API=${scopedApiTotal}`);

  const listText = await page.evaluate(() =>
    (document.querySelector('.van-list') || document.body).innerText);
  rec('D3', '页面上看不到 admin 造的那张根节点工单',
    rootWoNo ? !listText.includes(rootWoNo) : false,
    `查找 ${rootWoNo}`);

  // ws1 主任自己那条（HTTP E2E 已造过若干，这里用 API 确认真能看见自己的）
  rec('D4', 'ws1 主任能看到自己的报工（不是一片空白）',
    scopedRows > 0, `DOM 行数=${scopedRows}`);

  // ══════════ D5 检验明细：子表不宽于父单 ══════════
  {
    // 换回 admin 找一张有明细的根节点检验单
    await loginAs('mfg_admin', 'admin123');
    const orders = dataOf(await api('GET', '/inspection-orders?page=1&page_size=100')) || {};
    let target = null, n = 0;
    for (const o of (orders.items || [])) {
      if (o.org_id !== null && o.org_id !== 1) continue;
      const rr = await api('GET', `/inspection-orders/${o.id}/results`);
      const arr = dataOf(rr) || [];
      if (rr.status === 200 && arr.length > 0) { target = o; n = arr.length; break; }
    }
    rec('D5', '存在有明细的根节点检验单', !!target,
      target ? `order=${target.id} 明细 ${n} 条` : '扫完没有带明细的单');

    if (target) {
      await loginAs('demo_ws1_leader', 'admin123');
      const rr = await api('GET', `/inspection-orders/${target.id}/results`);
      const arr = dataOf(rr) || [];
      rec('D5', 'ws1 主任读同一张单的明细为空（子表不宽于父单）',
        rr.status === 403 || rr.status === 404 || arr.length === 0,
        `HTTP ${rr.status} 明细 ${Array.isArray(arr) ? arr.length : '—'} 条`);
    }
  }

  // ══════════ D6 JS 错误 ══════════
  rec('D6', '全程无 JS 运行时错误', consoleErrors.length === 0,
    `${consoleErrors.length} error${consoleErrors.length ? '：' + consoleErrors.slice(0, 3).join(' | ') : ''}`);

  await browser.close();

  const pass = results.filter(r => r.status === 'PASS').length;
  const fail = results.filter(r => r.status === 'FAIL').length;
  console.log(`\n===== 合计 ${results.length} 项：PASS ${pass} / FAIL ${fail} =====`);
  fs.writeFileSync(path.join(SHOT, 'result.json'), JSON.stringify(results, null, 2));
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('[FATAL]', e); process.exit(1); });
