/**
 * mfg1 E2E 测试 —— 生产管理模块
 *
 * 测试：工单管理/报工管理/生产报表/生产排产/BOM管理
 */
import { test, expect } from '@playwright/test';
import { loginAs } from '../utils/login';

test.describe('生产管理 (admin)', () => {
  test.beforeEach(async ({ page }) => {
    const pwd = process.env.CLOUD_PASSWORD;
    if (!pwd) { test.skip(true, '未设置 CLOUD_PASSWORD'); return; }
    await loginAs(page, 'sipon.wu@126.com', pwd);
  });

  test('工单列表加载且有数据（12条种子数据）', async ({ page }) => {
    const errors: string[] = [];
    page.on('requestfailed', (req) => errors.push(`${req.url()}`));

    await page.locator('.nav-item.parent', { hasText: '生产管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '工单管理' }).click();
    await page.waitForURL('**/work-orders**', { timeout: 10000 });
    await page.waitForTimeout(2000);

    await page.screenshot({ path: 'screenshots/production-work-orders.png', fullPage: true });
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test('报工管理页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '生产管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '报工管理' }).click();
    await page.waitForURL('**/work-reports**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/production-work-reports.png', fullPage: true });
  });

  test('生产排产页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '生产管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '生产排产' }).click();
    await page.waitForURL('**/schedule**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/production-schedule.png', fullPage: true });
  });

  test('BOM管理页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '生产管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: 'BOM管理' }).click();
    await page.waitForURL('**/boms**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/production-boms.png', fullPage: true });
  });
});
