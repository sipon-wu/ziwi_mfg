/**
 * mfg1 E2E 全角色全流程全覆盖全节点测试
 *
 * 组织方式：按角色分模块，逐个页面检查
 * 每个测试：
 *   1. 以当前角色登录
 *   2. 截图
 *   3. 监听 network error + HTTP 4xx/5xx + console error
 *   4. 记录所有错误到 buglist
 *
 * 注意：测试按顺序串行执行，避免 session 冲突
 */
import { test, expect, Page } from '@playwright/test';
import { loginAs, LOCAL_USERS, watchPageErrors, screenshotPage, PageError } from '../utils/login';

/* ============================================================
 * 模块页面 URL 映射（按 PRD 分组）
 * ============================================================ */
interface ModulePage {
  label: string;
  url: string;
}

// admin 可见的完整模块列表（allMenuTree 导出）
const ADMIN_MODULES: ModulePage[] = [
  // 首页
  { label: '驾驶舱', url: '/cockpit' },
  { label: '车间大屏', url: '/workshop' },

  // 基础数据
  { label: '工序定义', url: '/basics/operations' },
  { label: '工作中心', url: '/basics/work-centers' },
  { label: '工艺路线', url: '/basics/process-routes' },
  { label: '产品管理', url: '/basics/products' },
  { label: '工厂日历', url: '/basics/calendar' },

  // 生产管理
  { label: '工单管理', url: '/production/work-orders' },
  { label: '报工管理', url: '/production/work-reports' },
  { label: '生产排产', url: '/production/scheduling' },
  { label: 'BOM管理', url: '/production/bom' },
  { label: '生产报表', url: '/production/reports' },

  // 设备管理
  { label: '设备管理', url: '/equipment/devices' },
  { label: '保养任务', url: '/equipment/maintenance-tasks' },
  { label: '维护计划', url: '/equipment/maintenance-plans' },

  // 安灯管理
  { label: '安灯管理', url: '/andon/list' },
  { label: '升级规则', url: '/andon/escalation-rules' },

  // 品质管理
  { label: '品质管理', url: '/quality/inspection' },
  { label: 'SPC控制限', url: '/quality/spc' },
  { label: 'PPAP等级', url: '/quality/ppap-levels' },
  { label: 'PPAP提交', url: '/quality/ppap-submissions' },
  { label: 'PPAP要素', url: '/quality/ppap-elements' },
  { label: 'FMEA管理', url: '/quality/fmea' },

  // 能碳管理
  { label: '能碳管理', url: '/energy/dashboard' },
  { label: '用能概况', url: '/energy/overview' },
  { label: '能耗分析', url: '/energy/analysis' },
  { label: '碳管理', url: '/energy/carbon' },

  // 数据采集
  { label: '数据采集', url: '/data-collection/dashboard' },

  // 试产管理
  { label: '试产管理', url: '/trial/production' },

  // 实验室
  { label: '实验委托', url: '/lab/requests' },
  { label: '标准库', url: '/lab/standards' },

  // 系统管理
  { label: '系统配置', url: '/system/settings' },
  { label: '许可证', url: '/system/license' },
];

/* ============================================================
 * Bug 收集器
 * ============================================================ */
interface BugEntry {
  id: string;
  module: string;
  page: string;
  role: string;
  type: 'network_error' | 'http_error' | 'console_error' | 'navigation_fail' | 'menu_missing' | 'ui_anomaly';
  url: string;
  message: string;
  screenshot?: string;
}

let BUG_LIST: BugEntry[] = [];
let bugCounter = 0;

function addBug(bug: Omit<BugEntry, 'id'>) {
  bugCounter++;
  BUG_LIST.push({ ...bug, id: `BUG-${String(bugCounter).padStart(3, '0')}` });
}

/* ============================================================
 * 通用测试函数：导航到页面并检查错误
 * ============================================================ */
async function navigateAndCheck(
  page: Page,
  moduleLabel: string,
  pageItem: ModulePage,
  roleLabel: string
): Promise<void> {
  const stopWatching = watchPageErrors(page);

  try {
    const resp = await page.goto(pageItem.url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1000);

    // 检查是否跳到了登录页（表示该页面需要 auth 但未登录）
    if (page.url().includes('/login')) {
      addBug({
        module: moduleLabel,
        page: pageItem.label,
        role: roleLabel,
        type: 'navigation_fail',
        url: pageItem.url,
        message: `导航到 ${pageItem.url} 被重定向到登录页（可能 401/无权限）`,
      });
      return;
    }

    const errors = stopWatching();

    // 记录 HTTP 错误
    for (const err of errors.filter(e => e.type === 'http_error' && e.status >= 500)) {
      addBug({
        module: moduleLabel,
        page: pageItem.label,
        role: roleLabel,
        type: 'http_error',
        url: err.url,
        message: `HTTP ${err.status}: ${err.url}`,
      });
    }

    // 记录网络错误
    for (const err of errors.filter(e => e.type === 'network_error')) {
      addBug({
        module: moduleLabel,
        page: pageItem.label,
        role: roleLabel,
        type: 'network_error',
        url: err.url,
        message: err.message,
      });
    }

    // 记录 401（可能在页面内 XHR 触发）
    const authErrors = errors.filter(e => e.type === 'http_error' && e.status === 401);
    if (authErrors.length > 0) {
      addBug({
        module: moduleLabel,
        page: pageItem.label,
        role: roleLabel,
        type: 'http_error',
        url: authErrors[0].url,
        message: `未授权(401) — 页面内接口请求无 token，url=${authErrors[0].url}`,
      });
    }

    // 截图（仅 admin 全截，其他角色只截异常页）
    const safeName = `${roleLabel}-${pageItem.label}`.replace(/[\/\s]/g, '_');
    await screenshotPage(page, safeName);

  } catch (err: any) {
    addBug({
      module: moduleLabel,
      page: pageItem.label,
      role: roleLabel,
      type: 'navigation_fail',
      url: pageItem.url,
      message: `页面加载异常: ${err.message?.slice(0, 200)}`,
    });
  }
}

/* ============================================================
 * 测试开始
 * ============================================================ */

// ───── 1. 管理员全量测试 ─────
test.describe('E2E-01: 管理员全模块覆盖', () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    const user = LOCAL_USERS.admin;
    await loginAs(page, user.username, user.password);
  });

  test.afterAll(async () => {
    await page.close();
  });

  for (const mod of ADMIN_MODULES) {
    test(`[admin] ${mod.label} (${mod.url})`, async () => {
      test.setTimeout(60000);
      await navigateAndCheck(page, '全模块', mod, 'admin');
    });
  }
});

// ───── 2. 角色菜单可见性测试 ─────
test.describe('E2E-02: 角色权限菜单过滤', () => {
  const ROLE_CHECK_PAGES = [
    { label: '首页/驾驶舱', url: '/cockpit' },
    { label: '工单管理', url: '/production/work-orders' },
    { label: '服务管理', url: '/equipment/devices' },
    { label: '品质管理', url: '/quality/inspection' },
    { label: '能碳管理', url: '/energy/dashboard' },
    { label: '系统配置', url: '/system/settings' },
  ];

  for (const [roleKey, roleInfo] of Object.entries(LOCAL_USERS)) {
    if (roleKey === 'admin' || roleKey === 'mfg_admin') continue; // admin 已在 E2E-01 覆盖

    test(`${roleInfo.label} (${roleInfo.role}) 页面访问`, async ({ browser }) => {
      test.setTimeout(120000);
      const page = await browser.newPage();

      try {
        await loginAs(page, roleInfo.username, roleInfo.password);
      } catch (e: any) {
        addBug({
          module: '登录',
          page: 'login',
          role: roleInfo.label,
          type: 'navigation_fail',
          url: '/login',
          message: `${roleInfo.username} 登录失败: ${e.message?.slice(0, 200)}`,
        });
        await page.close();
        return;
      }

      // 检查该角色能访问的各页面
      for (const cp of ROLE_CHECK_PAGES) {
        const stopWatching = watchPageErrors(page);
        try {
          await page.goto(cp.url, { waitUntil: 'networkidle', timeout: 20000 });
          await page.waitForTimeout(800);
          const errors = stopWatching();

          // 记录所有 4xx/5xx
          for (const err of errors.filter(e => e.type === 'http_error' && e.status >= 400)) {
            addBug({
              module: '角色权限',
              page: cp.label,
              role: roleInfo.label,
              type: 'http_error',
              url: err.url,
              message: `角色 ${roleInfo.role} 访问 ${cp.url} → HTTP ${err.status}`,
            });
          }
        } catch {
          stopWatching();
        }
      }

      await page.close();
    });
  }
});

// ───── 3. 管理员关键业务操作测试 ─────
test.describe('E2E-03: 关键业务操作（admin）', () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    const user = LOCAL_USERS.admin;
    await loginAs(page, user.username, user.password);
  });

  test.afterAll(async () => {
    await page.close();
  });

  // 3.1 工单列表加载
  test('工单管理 — 列表加载', async () => {
    const stopWatching = watchPageErrors(page);
    await page.goto('/production/work-orders', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);

    // 检查表体是否有数据行
    const rows = page.locator('table tbody tr, .v-data-table__tr, .el-table__body-wrapper tr');
    const rowCount = await rows.count();
    if (rowCount === 0) {
      addBug({
        module: '生产管理', page: '工单列表', role: 'admin',
        type: 'ui_anomaly', url: '/production/work-orders',
        message: '工单列表页面无数据行（可能是 API 404 或页面组件渲染异常）',
      });
    }
    stopWatching();
  });

  // 3.2 设备列表加载
  test('设备管理 — 列表加载', async () => {
    const stopWatching = watchPageErrors(page);
    await page.goto('/equipment/devices', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);

    const rows = page.locator('table tbody tr, .v-data-table__tr, .el-table__body-wrapper tr');
    const rowCount = await rows.count();
    if (rowCount === 0) {
      addBug({
        module: '设备管理', page: '设备列表', role: 'admin',
        type: 'ui_anomaly', url: '/equipment/devices',
        message: '设备列表页面无数据行',
      });
    }

    // 截包含数据的图
    await screenshotPage(page, 'admin-设备列表');
    stopWatching();
  });

  // 3.3 安灯列表加载
  test('安灯管理 — 列表加载', async () => {
    const stopWatching = watchPageErrors(page);
    await page.goto('/andon/list', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);

    // 检查是否渲染了安灯卡片（有 KPI 数据就说明正常）
    const kpiCards = page.locator('.kpi-card, .stat-card, .metric-card, [class*=\"stat\"]');
    const kpiCount = await kpiCards.count();
    if (kpiCount === 0) {
      addBug({
        module: '安灯管理', page: '安灯列表', role: 'admin',
        type: 'ui_anomaly', url: '/andon/list',
        message: '安灯列表页面无 KPI 卡片/组件',
      });
    }
    stopWatching();
  });
});

// ───── 最终汇总 ─────
test.afterAll(async () => {
  // 输出 buglist
  console.log('\n========================================');
  console.log('📋 BUG LIST (全角色全流程)');
  console.log('========================================');
  if (BUG_LIST.length === 0) {
    console.log('✅ 未发现 Bug');
  } else {
    for (const bug of BUG_LIST) {
      console.log(`\n${bug.id} [${bug.type}] ${bug.module}/${bug.page}`);
      console.log(`   Role: ${bug.role}`);
      console.log(`   URL: ${bug.url}`);
      console.log(`   Msg: ${bug.message}`);
    }
  }
  console.log(`\n共发现 ${BUG_LIST.length} 个问题`);
  console.log('========================================');
});
