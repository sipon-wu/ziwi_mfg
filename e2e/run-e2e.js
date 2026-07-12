const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'https://mfg1.ziwi.cn';
const SCREENSHOT_DIR = path.join(__dirname, 'screenshots');
const PASSWORD = 'test123456';
const USERS = {
  test_admin: { role: 'admin', label: '管理员' },
  test_dept_head: { role: 'department_head', label: '部门主管' },
  test_team_leader: { role: 'team_leader', label: '班组长' },
  test_scheduler: { role: 'scheduler', label: '调度员' },
  test_proc_eng: { role: 'process_engineer', label: '工艺工程师' },
  test_key_user: { role: 'key_user', label: '关键用户' },
  test_maint_tech: { role: 'maintenance_tech', label: '维保员' },
  test_inspector: { role: 'inspector', label: '检验员' },
  test_quality_eng: { role: 'quality_engineer', label: '品质工程师' },
};

const PAGES = [
  '/cockpit', '/workshop',
  '/basics/operations', '/basics/work-centers', '/basics/process-routes', '/basics/products', '/basics/calendar',
  '/production/work-orders', '/production/work-reports', '/production/scheduling', '/production/bom', '/production/reports',
  '/equipment/devices', '/equipment/maintenance-tasks', '/equipment/maintenance-plans',
  '/andon/list', '/andon/escalation-rules',
  '/quality/inspection', '/quality/spc', '/quality/ppap-levels', '/quality/ppap-submissions', '/quality/ppap-elements', '/quality/fmea',
  '/energy/dashboard', '/energy/overview', '/energy/analysis', '/energy/carbon',
  '/data-collection/dashboard',
  '/trial/production',
  '/lab/requests', '/lab/standards',
  '/system/settings', '/system/license',
];

const BUGS = [];
let bugId = 0;

function logBug(module, page, role, type, url, message) {
  bugId++;
  const id = `BUG-${String(bugId).padStart(3, '0')}`;
  BUGS.push({ id, module, page, role, type, url, message });
  console.log(`  🐛 ${id} [${type}] ${role}/${page}: ${message}`);
}

async function main() {
  // Ensure screenshot dir
  if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });

  // ─── PHASE 1: Admin Full Coverage ───
  console.log('\n═══════════════════════════════════════');
  console.log('PHASE 1: 管理员全模块覆盖 (34 pages)');
  console.log('═══════════════════════════════════════');

  let adminCtx = await browser.newContext();
  let adminPage = await adminCtx.newPage();

  // Login as test_admin
  console.log('\n📌 登录 test_admin...');
  await adminPage.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await adminPage.waitForTimeout(1000);
  await adminPage.fill('input[placeholder*="用户名"], input[placeholder*="账号"]', 'test_admin');
  await adminPage.fill('input[placeholder*="密码"]', PASSWORD);
  await adminPage.click('button:has-text("登 录"), button:has-text("登录")');
  try { await adminPage.waitForURL('**/cockpit**', { timeout: 15000 }); }
  catch { logBug('登录', 'login', 'admin', 'navigation_fail', BASE + '/login', 'admin 登录后未跳转到 /cockpit'); }
  console.log('✅ admin 登录成功');

  // Navigate each page
  for (const url of PAGES) {
    console.log(`  ➡️  ${url}`);
    const errors = [];
    adminPage.on('response', (res) => {
      if (res.status() >= 400 && !res.url().includes('favicon')) {
        errors.push({ url: res.url(), status: res.status() });
      }
    });
    adminPage.on('requestfailed', (req) => {
      errors.push({ url: req.url(), msg: req.failure()?.errorText || 'failed' });
    });

    try {
      await adminPage.goto(`${BASE}${url}`, { waitUntil: 'networkidle', timeout: 20000 });
      await adminPage.waitForTimeout(1500);
    } catch (e) {
      logBug('全模块', url, 'admin', 'navigation_fail', url, '页面加载失败: ' + (e.message || '').slice(0, 100));
    }

    for (const e of errors) {
      logBug('全模块', url, 'admin', e.status ? 'http_error' : 'network_error', e.url, e.msg || `HTTP ${e.status}`);
    }

    // Screenshot
    const safeName = `admin_${url.replace(/\//g, '_')}`;
    await adminPage.screenshot({ path: `${SCREENSHOT_DIR}/${safeName}.png`, fullPage: true });
  }

  await adminPage.close();
  await adminCtx.close();

  // ─── PHASE 2: Role-based testing ───
  console.log('\n═══════════════════════════════════════');
  console.log('PHASE 2: 多角色权限验证 (8 roles × 6 pages)');
  console.log('═══════════════════════════════════════');

  const rolePages = ['/cockpit', '/production/work-orders', '/equipment/devices', '/quality/inspection', '/energy/dashboard', '/system/settings'];

  for (const [username, info] of Object.entries(USERS)) {
    if (username === 'test_admin') continue; // already done in Phase 1
    console.log(`\n📌 ${info.label} (${username}/${info.role})`);

    const ctx = await browser.newContext();
    const page = await ctx.newPage();

    try {
      await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(800);
      await page.fill('input[placeholder*="用户名"], input[placeholder*="账号"]', username);
      await page.fill('input[placeholder*="密码"]', PASSWORD);
      await page.click('button:has-text("登 录"), button:has-text("登录")');
      await page.waitForURL('**/cockpit**', { timeout: 15000 });
      console.log(`  ✅ 登录成功`);
    } catch (e) {
      logBug('登录', 'login', info.label, 'navigation_fail', BASE + '/login', `${username} 登录失败: ${e.message.slice(0, 100)}`);
      await page.close(); await ctx.close(); continue;
    }

    for (const rp of rolePages) {
      const errors = [];
      page.on('response', (res) => {
        if (res.status() >= 400 && !res.url().includes('favicon')) {
          errors.push({ url: res.url(), status: res.status() });
        }
      });
      page.on('requestfailed', (req) => {
        errors.push({ url: req.url(), msg: req.failure()?.errorText || 'failed' });
      });

      try {
        await page.goto(`${BASE}${rp}`, { waitUntil: 'networkidle', timeout: 15000 });
        await page.waitForTimeout(800);

        if (page.url().includes('/login')) {
          logBug('角色权限', rp, info.label, 'navigation_fail', rp, `${info.role} 访问 ${rp} 被重定向到登录页`);
        }
      } catch (e) {
        logBug('角色权限', rp, info.label, 'navigation_fail', rp, `${username} 访问 ${rp}: ${e.message.slice(0, 80)}`);
      }

      for (const e of errors) {
        logBug('角色权限', rp, info.label, e.status ? 'http_error' : 'network_error', e.url, e.msg || `HTTP ${e.status}`);
      }
    }
    await page.close(); await ctx.close();
  }

  // ─── REPORT ───
  await browser.close();

  console.log('\n\n═══════════════════════════════════════');
  console.log('📋 BUG LIST 最终报告');
  console.log('═══════════════════════════════════════');
  if (BUGS.length === 0) {
    console.log('✅ 未发现任何 Bug');
  } else {
    // Group by module
    const byModule = {};
    for (const b of BUGS) {
      if (!byModule[b.module]) byModule[b.module] = [];
      byModule[b.module].push(b);
    }
    for (const [mod, bugs] of Object.entries(byModule)) {
      console.log(`\n📁 ${mod} (${bugs.length} 个问题)`);
      for (const b of bugs) {
        console.log(`  ${b.id} [${b.type.padEnd(14)}] ${b.role.padEnd(10)} ${b.page.padEnd(30)} ${b.message}`);
      }
    }
  }
  console.log(`\n共发现 ${BUGS.length} 个问题`);
  console.log('═══════════════════════════════════════');

  // Write buglist to file
  const reportPath = path.join(__dirname, 'buglist.md');
  let md = '# mfg1 E2E 全角色全流程测试 Buglist\n\n';
  md += '测试时间: ' + new Date().toISOString() + '\n';
  md += '环境: mfg1.ziwi.cn (CVM 193.112.163.147)\n';
  md += '测试用户: 10 (admin + 9 角色)\n';
  md += '覆盖页面: ' + PAGES.length + ' 个\n\n';
  md += '## 汇总\n- 总问题数: ' + BUGS.length + '\n\n';
  md += '## 问题列表\n\n';

  for (const b of BUGS) {
    md += '### ' + b.id + ': [' + b.type + '] ' + b.module + '/' + b.page + '\n';
    md += '- **角色**: ' + b.role + '\n';
    md += '- **URL**: ' + b.url + '\n';
    md += '- **消息**: ' + b.message + '\n\n';
  }

  if (BUGS.length === 0) {
    md += '✅ 本次测试未发现 Bug。\n';
  }

  fs.writeFileSync(reportPath, md);
  console.log(`\n📄 报告已保存: ${reportPath}`);
}

main().catch(e => {
  console.error('FATAL:', e);
  process.exit(1);
});
