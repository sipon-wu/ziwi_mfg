// full_module_scan.js — 全模块覆盖扫描（Playwright/Chromium，headless）
// 目的：Beta 推进前的全面体检。覆盖全部路由（静态列表/看板页 + 详情页）+ 权限守卫。
// 前置：后端 8000 + 前端 5173 已启动，数据已 seed。
// 判定：
//   PASS = 页面渲染有实质内容 + 无 pageerror + 无新增 console error
//   WARN = 有内容，但有 console error（多为详情 id 不存在导致的 404，需人工判读）
//   FAIL = 白屏（body 空）或 pageerror
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// 本地默认打 5173（scripts/serve_alpha.js）；跑 staging 时传 BASE_URL=https://mfg1.ziwi.cn
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'full_module_scan');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  const tag = status === 'PASS' ? 'PASS' : status;
  console.log(`[${tag}] ${id} ${name} — ${detail}`);
}

// 全静态路由（不含 :id）
const STATIC_ROUTES = [
  ['/dashboard', '驾驶舱'],
  ['/workshop', '车间大屏'],
  ['/cockpit', '管理驾驶舱'],
  ['/work-orders', '工单列表'],
  ['/work-orders/create', '新建工单'],
  ['/work-reports', '报工列表'],
  ['/work-reports/create', '新建报工'],
  ['/reports', '报表'],
  ['/schedule', '生产排产'],
  ['/boms', 'BOM管理'],
  ['/basics/operations', '工序定义'],
  ['/basics/work-centers', '工作中心'],
  ['/basics/routes', '工艺路线'],
  ['/basics/products', '产品管理'],
  ['/basics/calendar', '工厂日历'],
  ['/equipment', '设备管理'],
  ['/equipment/create', '新增设备'],
  ['/equipment/maintenance-tasks', '保养任务'],
  ['/equipment/maintenance-plans', '维护计划'],
  ['/andon', '安灯管理'],
  ['/andon/escalation-rules', '升级规则'],
  ['/quality', '品质管理'],
  ['/quality/create', '新建检验'],
  ['/quality/ncr', '不合格评审'],
  ['/quality/spc/control-limits', 'SPC控制限'],
  ['/quality/ppap/levels', 'PPAP等级'],
  ['/quality/ppap/submissions', 'PPAP提交'],
  ['/quality/ppap/elements', 'PPAP要素'],
  ['/quality/fmea', 'FMEA管理'],
  ['/energy', '能碳设备'],
  ['/energy/overview', '用能概况'],
  ['/energy/analysis', '能耗分析'],
  ['/energy/carbon', '碳管理'],
  ['/data-collection', '数据采集'],
  ['/system/config', '系统配置'],
  ['/system/license', '许可证'],
  ['/wms/warehouse-tree', '仓库结构'],
  ['/wms/materials', '物料主数据'],
  ['/wms/receipt-orders', '入库单管理'],
  ['/wms/receipt-orders/create', '新建入库单'],
  ['/wms/issue-orders', '出库单管理'],
  ['/wms/stock-query', '库存查询'],
  ['/wms/stock-move', '库存移动'],
  ['/wms/inventory-counts', '盘点管理'],
  ['/wms/batches', '批次管理'],
  ['/wms/alerts', '库存预警'],
  ['/wms/reports', '库存报表'],
  ['/trials', '试产管理'],
  ['/trials/create', '新建试产'],
  ['/lab', '实验室'],
  ['/lab/standards', '标准库'],
  ['/setup', '方案配置'],
];

// 详情/编辑路由：id **不写死**，跑前先查列表取首条真实 id。
// 为什么：写死 id=1 只在本地 seed 出来的库成立。staging 真实首条工单 id 是 518、
// 设备是 101，于是这 13 条常年进 WARN，门禁就得靠人一条条判"这个 404 是数据没有
// 还是页面坏了"——结果就是 5 个 WARN 挂了很久没人动。探针要证明的是"页面能打开"，
// 不是"id=1 恰好存在"。
// 第三个元素 = 对应的列表端点；列表为空时记 OUT（无样本），不记 WARN。
const DETAIL_ROUTES = [
  ['/work-orders/{id}', '工单详情', '/work-orders'],
  ['/equipment/{id}', '设备详情', '/equipment'],
  ['/andon/{id}', '安灯详情', '/andon/calls'],
  ['/trials/{id}', '试产详情', '/trials'],
  ['/lab/{id}', '委托详情', '/lab/requests'],
  ['/quality/{id}', '检验详情', '/inspection-orders'],
  ['/basics/route-editor/{id}', '工艺路线编辑', '/routes'],
  ['/quality/spc/control-limits/{id}/chart', 'SPC控制图', '/spc/control-limits'],
  ['/quality/spc/control-limits/{id}/capability', '过程能力分析', '/spc/control-limits'],
  ['/quality/fmea/{id}/edit', 'FMEA编辑', '/fmea/documents'],
  ['/quality/fmea/{id}/actions', 'FMEA整改措施', '/fmea/documents'],
  ['/quality/fmea/{id}/control-plan', '控制计划', '/fmea/documents'],
  ['/wms/receipt-orders/{id}', '入库单详情', '/wms/receipt-orders'],
];

// 用页面自身的登录态去查列表（同源 fetch，不引第二个 HTTP 客户端，也不用猜 API 主机）。
// 取不到 id 的条目从扫描列表里摘掉并记 OUT —— 让"没样本"和"页面坏了"在结果里
// 是两种颜色，而不是混成一片 WARN 等人判读。
async function resolveDetailIds(page) {
  const kept = [];
  for (const item of DETAIL_ROUTES) {
    const [tpl, name, listPath] = item;
    const probe = await page.evaluate(async (p) => {
      // 后端统一包成 {code, message, data:{items,total}} 三层，且不同模块的
      // 集合键叫法不完全一样（items / list / rows）。只取一层会一律得到"0 条"——
      // 第一版就是这么错的：13 个详情页全记成 OUT，看着像"没数据"，其实是探针
      // 自己没把返回体解开。
      const firstRow = (node, depth) => {
        if (depth > 4 || node === null || node === undefined) return null;
        if (Array.isArray(node)) return node.length ? node[0] : null;
        if (typeof node !== 'object') return null;
        for (const k of ['items', 'data', 'list', 'rows', 'results', 'records']) {
          if (node[k] !== undefined) {
            const r = firstRow(node[k], depth + 1);
            if (r) return r;
          }
        }
        return null;
      };
      const token = localStorage.getItem('access_token') || '';
      const sep = p.includes('?') ? '&' : '?';
      try {
        const r = await fetch('/api/v1' + p + sep + 'page=1&page_size=1',
                              { headers: token ? { Authorization: 'Bearer ' + token } : {} });
        if (!r.ok) return { err: 'HTTP ' + r.status };
        const row = firstRow(await r.json(), 0);
        const id = row ? (row.id !== undefined ? row.id : row.ID) : null;
        return { id: id === undefined ? null : id };
      } catch (e) { return { err: String(e).slice(0, 60) }; }
    }, listPath);
    if (probe.id === null || probe.id === undefined) {
      rec('D:' + name, name, 'OUT', `列表无样本（${probe.err || '0 条'}），详情页本轮不探`);
      continue;
    }
    item[0] = tpl.replace('{id}', String(probe.id));
    kept.push(item);
  }
  DETAIL_ROUTES.length = 0;
  kept.forEach(x => DETAIL_ROUTES.push(x));
}

async function login(page, user, pw) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await new Promise(r => setTimeout(r, 600));
  await page.fill('input[placeholder="请输入用户名"]', user);
  await page.fill('input[placeholder="请输入密码"]', pw);
  await page.click('button[type="submit"]');
  await new Promise(r => setTimeout(r, 2600));
  return await page.evaluate(() => localStorage.getItem('access_token'));
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('[pageerror] ' + e.message));

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ── 登录 admin ──
  const token = await login(page, 'mfg_admin', 'admin123');
  rec('LOGIN', 'admin 登录', token ? 'PASS' : 'FAIL', `token=${!!token}`);

  // 先把详情页要用的 id 从真实数据里取出来，再开始扫
  await resolveDetailIds(page);

  async function scan(id, name, route) {
    const errBefore = consoleErrors.length;
    try {
      await page.goto(`${BASE}/#${route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(1000);
      const hash = await page.evaluate(() => location.hash);
      const bodyLen = await page.evaluate(() => document.body.innerText.trim().length);
      const newErrors = consoleErrors.slice(errBefore);
      const hasPageError = newErrors.some(e => e.startsWith('[pageerror]'));
      let status = 'PASS';
      if (bodyLen < 5 || hasPageError) status = 'FAIL';
      else if (newErrors.length) status = 'WARN';
      const shotName = id.replace(/[^a-zA-Z0-9]/g, '_');
      try { await page.screenshot({ path: path.join(SHOT, `${shotName}.png`), fullPage: false }); } catch {}
      rec(id, name, status, `hash=${hash}, body=${bodyLen}字, err=${newErrors.length}`);
      if (newErrors.length) console.log('      ↳ ' + newErrors.join(' | ').slice(0, 220));
    } catch (e) {
      rec(id, name, 'FAIL', (e.message || '').slice(0, 140));
    }
  }

  // ── A. 全静态路由 ──
  for (const [route, name] of STATIC_ROUTES) {
    await scan(`S:${route}`, name, route);
  }

  // ── B. 详情页 ──
  for (const [route, name] of DETAIL_ROUTES) {
    await scan(`D:${route}`, name, route);
  }

  // ── C. 权限守卫（受限角色访问受限页应被重定向 /403 或 /dashboard）──
  // S2 改造后，拦截目标是 /403（带 from / perm 参数），不再是 /dashboard。
  // 两者都算"被拦"，只要没真正进入目标页即可。
  const permToken = await login(page, 'test_inspector', 'test123456');
  rec('PERM-LOGIN', 'test_inspector 登录', permToken ? 'PASS' : 'FAIL', `token=${!!permToken}`);
  const permCases = [
    ['/quality/spc/control-limits', '检验员→SPC(需品质工程师)', true], // 应被拦
    ['/quality/ppap/levels', '检验员→PPAP(需品质工程师)', true],
    ['/quality/fmea', '检验员→FMEA(需品质工程师/工艺)', true],
    ['/quality', '检验员→品质管理(有权限)', false], // 应放行
    ['/basics/products', '检验员→产品管理(无角色限制)', false],
  ];
  for (const [route, name, shouldBlock] of permCases) {
    try {
      await page.goto(`${BASE}/#${route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(900);
      const hash = await page.evaluate(() => location.hash);
      const blocked = hash.includes('/403') || hash.includes('/dashboard') || hash.includes('/login');
      const ok = shouldBlock ? blocked : !blocked;
      rec(`P:${route}`, name, ok ? 'PASS' : 'FAIL', `期望${shouldBlock ? '拦截' : '放行'}, 实际hash=${hash}`);
    } catch (e) {
      rec(`P:${route}`, name, 'FAIL', (e.message || '').slice(0, 120));
    }
  }

  // ── 汇总 ──
  const pass = results.filter(r => r.status === 'PASS').length;
  const warn = results.filter(r => r.status === 'WARN').length;
  const fail = results.filter(r => r.status === 'FAIL').length;
  const out = results.filter(r => r.status === 'OUT').length;
  console.log(`\n════════ 全模块扫描汇总 ════════`);
  console.log(`PASS ${pass} / WARN ${warn} / FAIL ${fail} / OUT ${out} / TOTAL ${results.length}`);
  const fails = results.filter(r => r.status === 'FAIL');
  if (fails.length) { console.log('FAIL 明细：'); fails.forEach(f => console.log(`  ✗ ${f.id} ${f.name} — ${f.detail}`)); }
  const warns = results.filter(r => r.status === 'WARN');
  if (warns.length) { console.log('WARN 明细：'); warns.forEach(w => console.log(`  ⚠ ${w.id} ${w.name} — ${w.detail}`)); }

  fs.writeFileSync(path.join(__dirname, 'full_module_scan_result.json'), JSON.stringify({ ts: new Date().toISOString(), results, consoleErrors }, null, 2));
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
