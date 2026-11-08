// mfg1_e2e.js — mfg1 线上全链路仿真 E2E（真实浏览器 Playwright/Chromium）
// 覆盖 TC-00~08；数据全部带 E2E_BROWSER_ 前缀，保留不清理。
// 驱动方式：UI 登录 → 提取 JWT → 在浏览器上下文内 fetch 调后端（真实浏览器请求）+ WMS 页面导航冒烟。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'https://mfg1.ziwi.cn';
// 由 BASE 推导，避免「界面打 staging、API 打本地」两套环境混用
const API = (process.env.API_BASE || `${BASE}/api/v1`).replace(/\/$/, '');
const SHOT = path.join(__dirname, 'screenshots');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });
const PFX = 'E2E_BROWSER_';
const TS = Date.now();
// ★ 2026-11-09（B-19）：原来这里硬编码 `test_admin` / `test123456` —— 影子账号，
//   staging 上根本不存在。一次登录失败就连锁 401，九个用例全变成假红/假 BLOCKED，
//   而报告里的措辞（「后端无 /suppliers 路由」「BUG-5 阻断」）又把读者引向完全
//   无关的方向。改走环境变量，默认用 AH-THR 的真实账号（与
//   `_probe_kpi_state_e2e.js` 保持一致）。
const USER = process.env.E2E_USER || 'ah_admin';
const PWD = process.env.E2E_PWD || 'Ah@2026seed';
const TENANT = process.env.E2E_TENANT || 'AH-THR';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const log = (...a) => console.log(...a);

const results = [];
function record(id, name, status, detail, evidence) {
  results.push({ id, name, status, detail, evidence: evidence || null });
  log(`[${status}] ${id} ${name} — ${detail}`);
}
const rid = (b) => (b && b.request_id) || '';

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('[pageerror] ' + e.message));

  let token = null;
  async function uiLogin() {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1000);
    // ★ 不用 `#van-field-1-input` 这种 Vant 自动生成 id：登录表单加/删一个字段，
    //   编号就整体错位，而失败现场只会告诉你「登录不了」—— 极难联想到是选择器错。
    await page.fill('input[name="username"], input[type="text"]', USER);
    await page.fill('input[type="password"]', PWD);
    // 当前登录页**没有**租户输入框：`Login.vue::handleLogin` 只把用户名/密码交给
    // `auth.login()`，租户由后端按用户名解析。保留「有就填」的兼容分支，但别以为
    // 它能指定租户 —— 曾经因为它存在而误判「登录请求带了租户」。
    const tenantInput = await page.$('input[name="tenant_id"], input[name="tenant"]');
    if (tenantInput) await tenantInput.fill(TENANT);
    await page.click('button[type="submit"]');
    // ★ 等跳转**真的完成**再返回：`router.push('/cockpit')` 是异步导航，原来定长
    //   sleep(3000) 后在慢网络下仍读到 #/login，于是「已登录成功、七页全通」
    //   被判成 PARTIAL（2026-11-09 实测踩到）。
    await page
      .waitForFunction(() => !location.hash.includes('/login'), { timeout: 15000 })
      .catch(() => {});
    await sleep(500);
    return await page.evaluate(() => localStorage.getItem('access_token'));
  }
  async function api(method, p, body) {
    return await page.evaluate(async ({ method, url, body, token }) => {
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }, body: body ? JSON.stringify(body) : undefined });
      let data; try { data = await res.json(); } catch { try { data = await res.text(); } catch { data = ''; } }
      return { status: res.status, body: data };
    }, { method, url: API + p, body, token });
  }
  function firstId(listResp) {
    const d = listResp.body && listResp.body.data;
    if (!d) return null;
    const items = Array.isArray(d) ? d : (d.items || []);
    return items.length ? items[0].id : null;
  }
  const ids = {};

  // ===================== TC-00 登录与导航冒烟 =====================
  try {
    token = await uiLogin();
    ids.token = token;
    if (!token) {
      record('TC-00', '登录与导航冒烟', 'FAIL', 'UI 登录后无法从 localStorage 取得 access_token', null);
    } else {
      const url = page.url();
      const pages = [['#/cockpit', '驾驶舱'], ['#/work-orders', '工单管理'], ['#/boms', 'BOM'],
        ['#/wms/materials', '物料主数据'], ['#/wms/receipt-orders', '入库单'], ['#/wms/stock-query', '库存查询'], ['#/andon', '安灯']];
      const nav = [];
      for (const [route, title] of pages) {
        try {
          await page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle', timeout: 20000 });
          await sleep(1200);
          const txt = await page.evaluate(() => document.body.innerText.slice(0, 60).replace(/\n/g, ' '));
          const reachable = txt && txt.length > 3 && !/白屏|blank/i.test(txt);
          nav.push(`${title}:${reachable ? 'OK' : '空/重定向'}`);
          await page.screenshot({ path: path.join(SHOT, `tc00_${title}.png`) });
        } catch (e) { nav.push(`${title}:ERR`); }
      }
      const cockpitOk = url.includes('cockpit');
      record('TC-00', '登录与导航冒烟', cockpitOk ? 'PASS' : 'PARTIAL',
        `UI 登录成功，跳转 ${url}；关键页面渲染检查：${nav.join('，')}；控制台 error ${consoleErrors.length} 条（见 evidence）。`,
        { url, consoleErrors: consoleErrors.slice(0, 12) });
    }
  } catch (e) { record('TC-00', '登录与导航冒烟', 'FAIL', '异常: ' + e.message, null); }

  // ===================== TC-01 新建仿真工厂 =====================
  try {
    const t0 = await api('GET', '/tenants');
    record('TC-01', '新建仿真工厂', 'BLOCKED',
      `后端无独立工厂/Plant 管理模块（无 /factories、/plants 路由）；工厂/租户建档需经 cloud.ziwi.cn IdP 或 /tenants 管理员接口（${USER} 探活 /tenants → ${t0.status}）。按授权边界不在 AH-THR 内新建租户，故未创建任何工厂数据。需主理人/用户决策建模方式。`,
      { tenantsStatus: t0.status });
  } catch (e) { record('TC-01', '新建仿真工厂', 'FAIL', '异常: ' + e.message, null); }

  // ===================== TC-02 主数据准备 =====================
  try {
    const mat = await api('POST', '/wms/materials', { code: `${PFX}MAT_${TS}`, name: `${PFX}测试物料`, unit: 'pcs', material_type: 'raw', pick_strategy: 'fifo' });
    ids.matId = mat.body && mat.body.data && mat.body.data.id;
    const wh = await api('POST', '/wms/warehouses', { code: `${PFX}WH_${TS}`, name: `${PFX}测试原料仓`, type: 'raw_material' });
    ids.whId = wh.body && wh.body.data && wh.body.data.id;
    const loc = await api('POST', '/wms/locations', { warehouse_id: ids.whId, location_code: `${PFX}LOC_${TS}`, location_type: 'shelf' });
    ids.locId = loc.body && loc.body.data && loc.body.data.id;
    const sup = await api('GET', '/suppliers');
    const cus = await api('GET', '/customers');
    const ok = mat.status === 200 && wh.status === 200 && loc.status === 200;
    // ★ 2026-11-09 订正（B-19）：旧文案写「BOM 需产品主数据且工单下达链路被 BUG-5
    //   阻断；供应商/客户主数据：后端无 /suppliers、/customers 路由，无法建档」——
    //   三句全过时：
    //   ① BUG-5 早已修复，TC-04 现在能下达成功；
    //   ② 供应商已有只读接口（B-11 → C-78）。写接口**故意不做**：权威源在 ERP，
    //      MES 自建会让两边各存一份、对不上账（见 models/basic_data.Supplier 头注释）；
    //   ③ 客户确实没有路由，但同样不在 MES 范围 —— 是产品边界，不是缺陷。
    //   所以判定也跟着改：本用例的目标是「工厂内主数据就绪」，物料/仓库/库位
    //   三个都建成就 PASS。拿「不能建档」扣分等于把产品决策记成失败。
    const supNote = sup.status === 200
      ? '供应商 /suppliers 只读可用'
      : `/suppliers ${sup.status}`;
    const cusNote = cus.status === 404
      ? '客户 /customers 无路由'
      : `/customers ${cus.status}`;
    record('TC-02', '主数据准备(工厂内)', ok ? 'PASS' : 'FAIL',
      `物料 ${mat.status}(id=${ids.matId})；仓库 ${wh.status}(id=${ids.whId})；库位 ${loc.status}(id=${ids.locId})。`
      + `${supNote}；${cusNote}。供应商写接口缺失与客户无路由均属产品边界（B-11/C-78：主数据归 ERP/SRM，MES 只留快照），不是缺陷`,
      { matStatus: mat.status, whStatus: wh.status, locStatus: loc.status, suppliersStatus: sup.status, customersStatus: cus.status });
  } catch (e) { record('TC-02', '主数据准备(工厂内)', 'FAIL', '异常: ' + e.message, null); }

  // ===================== TC-03 采购→入库闭环 =====================
  try {
    if (!ids.matId || !ids.whId) {
      record('TC-03', '采购入库闭环', 'BLOCKED', '前置主数据未就绪，跳过', null);
    } else {
      const ro = await api('POST', '/wms/receipt-orders', {
        receipt_no: `${PFX}RO_${TS}`, receipt_type: 'purchase', warehouse_id: ids.whId,
        items: [{ line_no: 1, material_id: ids.matId, expected_qty: 100, received_qty: 100, unit: 'pcs', location_id: ids.locId, batch_no: `${PFX}B001` }]
      });
      const roId = ro.body && ro.body.data && ro.body.data.id;
      if (ro.status === 200) {
        const inv = await api('GET', `/wms/inventory?material_id=${ids.matId}`);
        record('TC-03', '采购入库闭环', 'PASS', `入库单创建成功 id=${roId}；库存校验见 evidence`, { roId, invStatus: inv.status });
      } else if (ro.status === 500) {
        record('TC-03', '采购入库闭环', 'BLOCKED', `入库单创建 500（已知 BUG-1），request_id=${rid(ro.body)}；库存无法增加，采购入库闭环中断。`, { status: ro.status, body: ro.body });
      } else {
        record('TC-03', '采购入库闭环', 'FAIL', `入库单创建 ${ro.status}: ${JSON.stringify(ro.body).slice(0, 200)}`, { status: ro.status, body: ro.body });
      }
    }
  } catch (e) { record('TC-03', '采购入库闭环', 'BLOCKED', '异常: ' + e.message, null); }

  // ===================== TC-04 生产工单闭环 =====================
  try {
    const wo = await api('POST', '/work-orders', { wo_no: `${PFX}WO_${TS}`, product_code: `${PFX}P01`, product_name: `${PFX}测试产品`, planned_qty: 50 });
    const wl = await api('GET', `/work-orders?keyword=${PFX}WO_${TS}`);
    ids.woId = firstId(wl);
    let releaseDetail, issueDetail = '未执行', wrDetail = '跳过';
    if (ids.woId) {
      const rel = await api('POST', `/work-orders/${ids.woId}/release`, { force_release: true, force_reason: 'E2E探针' });
      releaseDetail = rel.status === 200 ? '下达成功' : (rel.status === 500 ? `下达500(已知BUG-5) req=${rid(rel.body)}` : `下达${rel.status}`);
    } else {
      releaseDetail = '无法获取工单ID（创建响应缺 data.id）';
    }
    if (ids.matId && ids.whId) {
      const io = await api('POST', '/wms/issue-orders', { issue_no: `${PFX}IO_${TS}`, issue_type: 'production', warehouse_id: ids.whId, items: [{ line_no: 1, material_id: ids.matId, required_qty: 10, issued_qty: 10, unit: 'pcs', from_location_id: ids.locId }] });
      issueDetail = io.status === 500 ? `领料出库500(已知BUG-2/3) req=${rid(io.body)}` : `领料出库 ${io.status}`;
    }
    let completedQty = null;
    let snapshotCount = null;
    if (ids.woId) {
      const wr = await api('POST', '/work-reports', { work_order_id: ids.woId, report_date: new Date().toISOString().slice(0, 10), output_qty: 5, input_qty: 5 });
      wrDetail = wr.status === 200 ? '报工成功' : `报工 ${wr.status}`;
      if (wr.status === 200) {
        // ★ 2026-11-09 补真验证（B-19）：旧文案把「completed_qty 回写未验证」
        //   写死在字符串里 —— 等于永远不验，还每次跑都把这个结论原样打出来。
        //   现在报工后回读工单，直接看回写值；同时对 BOM 快照取条数。
        const wd = await api('GET', `/work-orders/${ids.woId}`);
        completedQty = wd.body && wd.body.data ? wd.body.data.completed_qty : null;
        const sn = await api('GET', `/boms/snapshots?work_order_id=${ids.woId}`);
        const list = sn.body && sn.body.data
          ? (Array.isArray(sn.body.data) ? sn.body.data : (sn.body.data.items || []))
          : [];
        snapshotCount = list.length;
      }
    }
    const blocked = releaseDetail.includes('500') || issueDetail.includes('500');
    // 完成判据：下达成功 + 报工成功 + completed_qty 真的回写成 5。
    // ★ 快照条数**只报不判**：本用例没建产品/BOM 主数据，无 BOM 的工单下达后
    //   快照 0 条是**正确行为**，判成缺陷就是假红；要真做齐套比对必须另建前置
    //   （产品 + BOM + 路线），不能在这个用例里靠 0 条蒙。
    const closedLoop = releaseDetail === '下达成功' && wrDetail === '报工成功' && completedQty === 5;
    record('TC-04', '生产工单闭环', blocked ? 'BLOCKED' : (closedLoop ? 'PASS' : 'FAIL'),
      `工单创建 ${wo.status}(id=${ids.woId})；下达: ${releaseDetail}；领料: ${issueDetail}；报工: ${wrDetail}；`
      + `completed_qty 回读=${completedQty === null ? '取不到' : completedQty}（期望 5）；`
      + `BOM 快照 ${snapshotCount === null ? '未取' : snapshotCount} 条`
      + '（本用例无产品/BOM 主数据，0 条属正常，未做齐套比对）',
      { woStatus: wo.status, releaseDetail, issueDetail, wrDetail, completedQty, snapshotCount });
  } catch (e) { record('TC-04', '生产工单闭环', 'BLOCKED', '异常: ' + e.message, null); }

  // ===================== TC-05 销售出库闭环 =====================
  try {
    if (!ids.matId || !ids.whId) {
      record('TC-05', '销售出库闭环', 'BLOCKED', '前置主数据未就绪，跳过', null);
    } else {
      const io = await api('POST', '/wms/issue-orders', { issue_no: `${PFX}SO_${TS}`, issue_type: 'sales', warehouse_id: ids.whId, items: [{ line_no: 1, material_id: ids.matId, required_qty: 5, issued_qty: 5, unit: 'pcs', from_location_id: ids.locId }] });
      const so = await api('GET', '/sales-orders');
      if (io.status === 200) {
        const inv = await api('GET', `/wms/inventory?material_id=${ids.matId}`);
        record('TC-05', '销售出库闭环', 'PASS', `销售出库(issue)成功；库存校验见 evidence；销售订单主数据 /sales-orders → ${so.status}`, { soStatus: so.status, invStatus: inv.status });
      } else if (io.status === 500) {
        record('TC-05', '销售出库闭环', 'BLOCKED', `销售出库(issue) 500（已知 BUG-2/3）req=${rid(io.body)}；销售订单主数据：后端无 /sales-orders 路由(${so.status})。`, { ioStatus: io.status, salesOrdersStatus: so.status });
      } else {
        record('TC-05', '销售出库闭环', 'FAIL', `销售出库 ${io.status}: ${JSON.stringify(io.body).slice(0, 200)}`, { ioStatus: io.status, salesOrdersStatus: so.status });
      }
    }
  } catch (e) { record('TC-05', '销售出库闭环', 'BLOCKED', '异常: ' + e.message, null); }

  // ===================== TC-06 库存联动与数据对不拢核对 =====================
  try {
    const ss = await api('GET', '/wms/reports/stock-summary');
    const inv = await api('GET', '/wms/inventory');
    const tx = await api('GET', '/wms/inventory-transactions');
    if (ss.status === 500) {
      record('TC-06', '库存联动与数据对不拢核对', 'BLOCKED',
        `库存汇总 stock-summary 500（已知 BUG-4）req=${rid(ss.body)}；无法做收发存汇总对账。库存列表 ${inv.status}、流水 ${tx.status} 可查但无闭环数据联动可验。`,
        { ssStatus: ss.status, invStatus: inv.status, txStatus: tx.status });
    } else {
      record('TC-06', '库存联动与数据对不拢核对', 'PARTIAL', `stock-summary ${ss.status}；库存 ${inv.status}；流水 ${tx.status}，见 evidence`, { ss, inv, tx });
    }
  } catch (e) { record('TC-06', '库存联动与数据对不拢核对', 'BLOCKED', '异常: ' + e.message, null); }

  // ===================== TC-07 异常与看板 =====================
  try {
    const andon = await api('POST', '/andon/calls', { call_type: 'material', title: `${PFX}缺料呼叫`, level: 'urgent', source: 'manual', description: 'E2E浏览器测试触发', work_order_id: ids.woId || null });
    const andonOk = andon.status === 200 || andon.status === 201;
    // ★原来这里写死了一句「看板数值与底层一致性因汇总接口 500 无法自动核对」，
    //   是 7 月的状态文案，脚本压根没去调汇总接口 —— 每次跑都把这个陈旧结论
    //   原样打出来，等于用一个假信号掩盖了"其实没测"。改成真调一次。
    const summ = await api('GET', '/wms/reports/summary');
    const summOk = summ.status === 200;
    record('TC-07', '异常与看板', andonOk && summOk ? 'PASS' : 'FAIL',
      `安灯呼叫 ${andon.status}｜库存快照接口 ${summ.status}`,
      { andonStatus: andon.status, summaryStatus: summ.status });
  } catch (e) { record('TC-07', '异常与看板', 'PARTIAL', '异常: ' + e.message, null); }

  // ===================== TC-08 跨模块一致性总核对 =====================
  try {
    const matrix = {
      work_order_id: ids.woId, material_id: ids.matId, warehouse_id: ids.whId,
      note: '浏览器侧只登记矩阵编号；四方对账断言由 e2e/quad_reconcile_e2e.py 实现（守恒式 + 三账一致 + 负向自证），已纳入 run_all.py。'
    };
    record('TC-08', '跨模块一致性总核对', 'BLOCKED',
      // ★四方对账已由独立 Python 探针实现，本用例仍只登记 id、不做断言，
      //   所以状态保持 BLOCKED；但文案不能再说「逻辑尚未实现」。
      `工单(${ids.woId})-库存-流水-看板：浏览器侧仅登记矩阵编号，断言见 e2e/quad_reconcile_e2e.py（已纳入 run_all.py）。本用例不做断言，勿当成已验证。`,
      matrix);
    fs.writeFileSync(path.join(__dirname, 'consistency-matrix.json'), JSON.stringify(matrix, null, 2));
  } catch (e) { record('TC-08', '跨模块一致性总核对', 'BLOCKED', '异常: ' + e.message, null); }

  // ---- 汇总 ----
  const summary = { total: results.length, PASS: 0, PARTIAL: 0, FAIL: 0, BLOCKED: 0 };
  results.forEach(r => summary[r.status]++);
  const out = { generatedAt: new Date().toISOString(), base: BASE, prefix: PFX, summary, results, createdIds: ids };
  fs.writeFileSync(path.join(__dirname, 'mfg1_e2e_result.json'), JSON.stringify(out, null, 2));
  log('\n========== E2E 汇总 ==========');
  log(JSON.stringify(summary));
  log('结果已写入 mfg1_e2e_result.json');
  await browser.close();
})().catch(e => { console.error('致命错误:', e); process.exit(1); });
