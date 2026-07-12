/**
 * mfg1 E2E 测试 —— 首页 & 菜单检查
 *
 * 测试范围：
 * - 登录后跳转到 /cockpit
 * - admin 可见所有菜单项
 * - 截图首页各组件
 */
import { test, expect } from '@playwright/test';
import { loginAs } from '../utils/login';
import { ALL_MENU_ITEMS, checkNoPageErrors } from '../utils/navigation';

test.describe('登录 & 菜单检查 (admin)', () => {
  let errors: string[];

  test.beforeEach(async ({ page }) => {
    // 使用 cloud 管理员账号登录（需设置 CLOUD_PASSWORD 环境变量）
    const pwd = process.env.CLOUD_PASSWORD;
    if (!pwd) {
      test.skip(!pwd, '未设置 CLOUD_PASSWORD 环境变量');
      return;
    }
    await loginAs(page, 'sipon.wu@126.com', pwd);
  });

  test('登录后跳转到 /cockpit', async ({ page }) => {
    await expect(page).toHaveURL(/\/cockpit/);
  });

  test('admin 可见所有菜单项', async ({ page }) => {
    for (const menu of ALL_MENU_ITEMS) {
      // 验证父菜单可见
      await expect(page.locator('.nav-item.parent', { hasText: menu.label })).toBeVisible();
      // 展开并验证子菜单
      await page.locator('.nav-item.parent', { hasText: menu.label }).click();
      await page.waitForTimeout(300);
      for (const child of menu.children) {
        await expect(page.locator('.nav-item.sub', { hasText: child })).toBeVisible();
      }
    }
  });

  test('驾驶舱页面无网络错误', async ({ page }) => {
    errors = [];
    page.on('requestfailed', (req) => {
      errors.push(`${req.url()} — ${req.failure()?.errorText}`);
    });

    await page.goto('/cockpit');
    await page.waitForTimeout(2000);

    await page.screenshot({ path: 'screenshots/cockpit.png', fullPage: true });
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test('车间大屏页面无网络错误', async ({ page }) => {
    errors = [];
    page.on('requestfailed', (req) => {
      errors.push(`${req.url()} — ${req.failure()?.errorText}`);
    });

    await page.goto('/workshop');
    await page.waitForTimeout(2000);

    await page.screenshot({ path: 'screenshots/workshop.png', fullPage: true });
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });
});
