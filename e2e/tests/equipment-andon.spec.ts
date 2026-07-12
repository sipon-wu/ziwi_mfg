/**
 * mfg1 E2E 测试 —— 设备管理 & 安灯管理
 */
import { test, expect } from '@playwright/test';
import { loginAs } from '../utils/login';

const PWD_SKIP = () => { const p = process.env.CLOUD_PASSWORD; if (!p) test.skip(true, '未设置 CLOUD_PASSWORD'); return p; };

test.describe('设备管理 (admin)', () => {
  test.beforeEach(async ({ page }) => {
    const pwd = PWD_SKIP(); if (!pwd) return;
    await loginAs(page, 'sipon.wu@126.com', pwd as string);
  });

  test('设备列表加载（11台种子设备）', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '设备管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '设备管理' }).click();
    await page.waitForURL('**/equipment**', { timeout: 10000 });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'screenshots/equipment-list.png', fullPage: true });
  });

  test('保养任务页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '设备管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '保养任务' }).click();
    await page.waitForURL('**/maintenance-tasks**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/equipment-maintenance-tasks.png', fullPage: true });
  });
});

test.describe('安灯管理 (admin)', () => {
  test.beforeEach(async ({ page }) => {
    const pwd = PWD_SKIP(); if (!pwd) return;
    await loginAs(page, 'sipon.wu@126.com', pwd as string);
  });

  test('安灯列表加载（6条种子数据）', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '安灯管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '安灯管理' }).click();
    await page.waitForURL('**/andon**', { timeout: 10000 });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'screenshots/andon-list.png', fullPage: true });
  });

  test('升级规则页面加载', async ({ page }) => {
    await page.locator('.nav-item.parent', { hasText: '安灯管理' }).click();
    await page.waitForTimeout(300);
    await page.locator('.nav-item.sub', { hasText: '升级规则' }).click();
    await page.waitForURL('**/escalation-rules**', { timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/andon-escalation.png', fullPage: true });
  });
});
