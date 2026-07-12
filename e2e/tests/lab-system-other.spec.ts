/**
 * mfg1 E2E 测试 —— 实验室 & 系统管理 & 数据采集 & 试产
 */
import { test, expect } from '@playwright/test';
import { loginAs } from '../utils/login';

const PWD_SKIP = () => { const p = process.env.CLOUD_PASSWORD; if (!p) test.skip(true, '未设置 CLOUD_PASSWORD'); return p; };

test.describe('实验室 & 系统 & 数据采集 & 试产 (admin)', () => {
  test.beforeEach(async ({ page }) => {
    const pwd = PWD_SKIP() as string; if (!pwd) return;
    await loginAs(page, 'sipon.wu@126.com', pwd);
  });

  test('实验室 → 实验委托 页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '实验室' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '实验委托' }).click();
    await page.waitForURL('**/lab**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/lab-requests.png', fullPage: true });
  });

  test('实验室 → 标准库 页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '实验室' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '标准库' }).click();
    await page.waitForURL('**/lab/standards**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/lab-standards.png', fullPage: true });
  });

  test('系统管理 → 系统配置 页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '系统管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '系统配置' }).click();
    await page.waitForURL('**/system/config**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/system-config.png', fullPage: true });
  });

  test('系统管理 → 许可证 页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '系统管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '许可证' }).click();
    await page.waitForURL('**/system/license**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/system-license.png', fullPage: true });
  });

  test('数据采集 页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '数据采集' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '数据采集' }).click();
    await page.waitForURL('**/data-collection**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/data-collection.png', fullPage: true });
  });

  test('试产管理 页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '试产管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '试产工单' }).click();
    await page.waitForURL('**/trials**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/trials.png', fullPage: true });
  });
});
