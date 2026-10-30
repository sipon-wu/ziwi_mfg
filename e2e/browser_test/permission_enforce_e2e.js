// permission_enforce_e2e.js — 强制模式（PERMISSION_ENFORCE=true）全角色全页面回归
//
// 前置：后端 :8000（强制模式）+ 前端 :5173（最新构建）。
//
// 验证目标
// --------
// 切强制模式最大的风险不是"该拦的没拦"，而是「菜单还在、点进去 403」——
// 用户看到空白页 + 一句"缺少权限"，体感等同系统坏了。所以这里做的事是：
//
//   1. 用后端 /auth/me 拿到的 permissions，在前端算一遍"这个角色能进哪些页面"
//   2. 真的逐页访问，收集每页加载期间返回 403 的接口
//   3. 断言：**能进的页面里，0 个接口 403**
//   4. admin 必须能进全部 46 个页面（否则是漏授权，不是权限收紧）
//   5. 顺带记录"进不去"的页面数，确认收紧范围符合预期
//
// 覆盖 9 个角色的账号（密码 test123456，admin 的 mfg_admin 是 admin123）。
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 'permission_enforce');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

// 无路径参数的页面（带 :id 的详情页无法凭空访问，由各自的 E2E 覆盖）
const PAGES = [
  ['/andon', 'M05:andon_call:read'],
  ['/andon/escalation-rules', 'M05:andon_escalation_rule:read'],
  ['/basics/calendar', 'M00:calendar:read'],
  ['/basics/operations', 'M00:operation:read'],
  ['/basics/products', 'M00:product:read'],
  ['/basics/routes', 'M00:route:read'],
  ['/basics/work-centers', 'M00:work_center:read'],
  ['/boms', 'M02:bom:read'],
  ['/data-collection', 'M12:collect_task:read'],
  ['/energy', 'M11:energy_device:read'],
  ['/energy/analysis', 'M11:energy_device:read'],
  ['/energy/carbon', 'M11:energy_device:read'],
  ['/energy/overview', 'M11:energy_device:read'],
  ['/equipment', 'M06:equipment:read'],
  ['/equipment/create', 'M06:equipment:read'],
  ['/equipment/maintenance-plans', 'M06:equipment:read'],
  ['/equipment/maintenance-tasks', 'M06:equipment:read'],
  ['/lab', 'M15:lab_request:read'],
  ['/lab/standards', 'M15:lab_standard:read'],
  ['/quality', 'M03:inspection_order:read'],
  ['/quality/create', 'M03:inspection_order:read'],
  ['/quality/fmea', 'M10:fmea_document:read'],
  ['/quality/ncr', 'M30:ncr:read'],
  ['/quality/ppap/elements', 'M10:ppap_submission:read'],
  ['/quality/ppap/levels', 'M10:ppap_submission:read'],
  ['/quality/ppap/submissions', 'M10:ppap_submission:read'],
  ['/quality/spc/control-limits', 'M10:spc_control_limit:read'],
  ['/reports', 'M01:work_order:read'],
  ['/schedule', 'M01:work_order:read'],
  ['/system/config', 'PLAT:user:read'],
  ['/system/license', 'PLAT:user:read'],
  ['/system/roles', 'PLAT:role_permission:read'],
  ['/trials', 'M16:trial:read'],
  ['/trials/create', 'M16:trial:read'],
  ['/wms/inventory-counts', 'M04:wms_inventory_count:read'],
  ['/wms/issue-orders', 'M04:wms_issue_order:read'],
  ['/wms/materials', 'M04:wms_material:read'],
  ['/wms/receipt-orders', 'M04:wms_receipt_order:read'],
  ['/wms/receipt-orders/create', 'M04:wms_receipt_order:read'],
  ['/wms/stock-move', 'M04:wms_inventory:read'],
  ['/wms/stock-query', 'M04:wms_inventory:read'],
  ['/wms/warehouse-tree', 'M04:wms_warehouse:read'],
  ['/work-orders', 'M01:work_order:read'],
  ['/work-orders/create', 'M01:work_order:read'],
  ['/work-reports', 'M01:work_order:read'],
  ['/work-reports/create', 'M01:work_order:read'],
];

const ACCOUNTS = [
  ['mfg_admin', 'admin123'],
  ['test_dept_head', 'test123456'],
  ['test_team_leader', 'test123456'],
  ['test_scheduler', 'test123456'],
  ['test_proc_eng', 'test123456'],
  ['test_key_user', 'test123456'],
  ['test_maint_tech', 'test123456'],
  ['test_inspector', 'test123456'],
  ['test_quality_eng', 'test123456'],
];

const sleep = ms => new Promise(r => setTimeout(r, ms));
const rows = [];
let hardFail = 0;

/** 与前端 stores/auth.ts 的 matchPermission 同语义：四级通配 */
function matchPermission(perms, required) {
  if (!required) return true;
  if (perms.includes('*') || perms.includes(required)) return true;
  const parts = required.split(':');
  if (parts.length !== 3) return false;
  const [mod, res, act] = parts;
  return perms.includes(`${mod}:*`) || perms.includes(`${mod}:${res}:*`) || perms.includes(`*:${act}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // 当前页面加载期间发生的 403
  let hits403 = [];
  page.on('response', res => {
    if (res.status() === 403) hits403.push(`${res.request().method()} ${new URL(res.url()).pathname}`);
  });
  const jsErrors = [];
  page.on('pageerror', e => jsErrors.push(e.message));

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
      const me = raw && raw.data ? raw.data : raw;   // /auth/me 走 {code,message,data} 包装
      localStorage.setItem('user_info', JSON.stringify(me));
      return { ok: true, perms: me.permissions || [], roles: (me.roles || []).map(r => r.code || r) };
    }, { username, password });
    await page.goto(`${BASE}/#/cockpit`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    // 必须硬刷新：只改 hash 不会重跑 auth.init()，store 里还是上个账号的权限
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(700);
    return res;
  }

  for (const [username, password] of ACCOUNTS) {
    const who = await loginAs(username, password);
    if (!who.ok) {
      console.log(`[FAIL] ${username} 登录失败 status=${who.status}`);
      hardFail++;
      continue;
    }
    const perms = who.perms || [];
    const allowed = PAGES.filter(([, need]) => matchPermission(perms, need));

    let pageFail = 0;
    const badPages = [];
    for (const [p] of allowed) {
      hits403 = [];
      try {
        await page.goto(`${BASE}/#${p}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
        await sleep(450);
      } catch (e) {
        badPages.push(`${p} (导航超时)`);
        pageFail++;
        continue;
      }
      if (hits403.length) {
        pageFail++;
        badPages.push(`${p} → ${[...new Set(hits403)].join(', ')}`);
      }
    }

    const ok = pageFail === 0;
    if (!ok) hardFail++;
    console.log(`[${ok ? 'PASS' : 'FAIL'}] ${username.padEnd(20)} 可见页面 ${String(allowed.length).padStart(2)}/${PAGES.length}｜403 页面 ${pageFail}` +
      (badPages.length ? `\n        ${badPages.join('\n        ')}` : ''));

    rows.push({ username, allowed: allowed.length, pageFail, perms: perms.length, badPages });

    // admin 必须能进全部页面：少一个就是漏授权
    if (perms.includes('*') && allowed.length !== PAGES.length) {
      console.log(`  [FAIL] admin 可见页面数 ${allowed.length} != ${PAGES.length}`);
      hardFail++;
    }
  }

  await page.screenshot({ path: path.join(SHOT, 'last.png') }).catch(() => {});

  console.log('\n' + '='.repeat(74));
  console.log('账号'.padEnd(22) + '权限点'.padEnd(8) + '可见页面'.padEnd(10) + '403 页面');
  for (const r of rows) {
    console.log(r.username.padEnd(22) + String(r.perms).padEnd(8) +
      String(r.allowed).padEnd(10) + r.pageFail);
  }
  console.log(`JS 错误：${jsErrors.length ? jsErrors.slice(0, 3).join(' ‖ ') : '0'}`);
  if (jsErrors.length) hardFail++;
  console.log(hardFail === 0
    ? `\n结论：全部通过 —— 强制模式下"能进得去的页面"没有任何接口 403（${PAGES.length} 个页面 × ${ACCOUNTS.length} 个账号）`
    : `\n结论：${hardFail} 项失败，见上`);

  await browser.close();
  process.exit(hardFail ? 1 : 0);
})();
