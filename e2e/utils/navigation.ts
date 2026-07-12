import { Page, expect } from '@playwright/test';

/**
 * 菜单路径定义（与前端 MainLayout.vue 的 allMenuTree 一致）
 */
export const ALL_MENU_ITEMS = [
  { menu: '首页', label: '首页', children: ['驾驶舱', '车间大屏'] },
  { menu: '基础数据', label: '基础数据', children: ['工序定义', '工作中心', '工艺路线', '产品管理', '工厂日历'] },
  { menu: '生产管理', label: '生产管理', children: ['工单管理', '报工管理', '生产报表', '生产排产', 'BOM管理'] },
  { menu: '设备管理', label: '设备管理', children: ['设备管理', '保养任务', '维护计划'] },
  { menu: '安灯管理', label: '安灯管理', children: ['安灯管理', '升级规则'] },
  { menu: '品质管理', label: '品质管理', children: ['品质管理', 'SPC控制限', 'PPAP等级', 'PPAP提交', 'PPAP要素', 'FMEA管理'] },
  { menu: '能碳管理', label: '能碳管理', children: ['能碳管理', '用能概况', '能耗分析', '碳管理'] },
  { menu: '数据采集', label: '数据采集', children: ['数据采集'] },
  { menu: '试产管理', label: '试产管理', children: ['试产工单'] },
  { menu: '实验室', label: '实验室', children: ['实验委托', '标准库'] },
  { menu: '系统管理', label: '系统管理', children: ['系统配置', '许可证'] },
];

/**
 * 权限矩阵（与前端 menu-permissions.ts 一致）
 * role_codes 为 undefined/空 → 所有角色可见
 * 具体角色 → 仅该角色可见
 */
export interface MenuPermission {
  menuId: string;
  roles?: string[];
  children?: { childId: string; roles: string[] }[];
}

/**
 * 记录页面错误并截图
 */
export async function checkNoPageErrors(page: Page): Promise<string[]> {
  const errors: string[] = [];

  // 监听控制台错误
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push(`[CONSOLE] ${msg.text()}`);
    }
  });

  // 监听网络请求失败
  page.on('requestfailed', (request) => {
    errors.push(`[NETWORK] ${request.url()} (${request.failure()?.errorText})`);
  });

  return errors;
}

/**
 * 导航到子页面并验证无错误
 */
export async function navigateToChild(
  page: Page,
  parentLabel: string,
  childLabel: string,
  path: string
): Promise<string[]> {
  // 点击父菜单展开
  const parentBtn = page.locator('.nav-item.parent', { hasText: parentLabel });
  if (await parentBtn.isVisible()) {
    await parentBtn.click();
    await page.waitForTimeout(500);
  }

  // 点击子菜单
  const childLink = page.locator('.nav-item.sub', { hasText: childLabel });
  if (await childLink.isVisible()) {
    await childLink.click();
    await page.waitForURL(`**${path}**`, { timeout: 10000 });
    await page.waitForTimeout(1000);
  }

  // 检查页面错误
  const errors: string[] = [];
  const networkErrors = await checkNoPageErrors(page);
  errors.push(...networkErrors);

  // 检查 HTTP 响应状态
  await page.screenshot({ path: `screenshots/page-${childLabel.replace(/\//g, '-')}.png`, fullPage: true });

  return errors;
}

/**
 * 验证菜单项是否可见
 */
export async function verifyMenuVisible(page: Page, menuLabel: string, expected: boolean) {
  // 展开父菜单
  const parentBtn = page.locator('.nav-item.parent', { hasText: menuLabel });
  if (expected) {
    await expect(parentBtn.first()).toBeVisible({ timeout: 5000 });
  }
}

/**
 * 验证子菜单项是否可见
 */
export async function verifyChildVisible(page: Page, parentLabel: string, childLabel: string, expected: boolean) {
  // 展开父菜单
  const parentBtn = page.locator('.nav-item.parent', { hasText: parentLabel });
  if (await parentBtn.isVisible()) {
    await parentBtn.click();
    await page.waitForTimeout(500);
  }

  const childLink = page.locator('.nav-item.sub', { hasText: childLabel });
  if (expected) {
    await expect(childLink.first()).toBeVisible({ timeout: 3000 });
  } else {
    await expect(childLink.first()).not.toBeVisible({ timeout: 3000 });
  }
}
