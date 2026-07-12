/**
 * mfg1 E2E 测试 —— 品质管理模块
 */
import { test, expect } from '@playwright/test';
import { loginAs } from '../utils/login';

const PWD_SKIP = () => { const p = process.env.CLOUD_PASSWORD; if (!p) test.skip(true, '未设置 CLOUD_PASSWORD'); return p; };

test.describe('品质管理 (admin)', () => {
  test.beforeEach(async ({ page }) => {
    const pwd = PWD_SKIP() as string; if (!pwd) return;
    await loginAs(page, 'sipon.wu@126.com', pwd);
  });

  const pages = [
    { label: '品质管理', path: '/quality' },
    { label: 'SPC控制限', path: '/quality/spc/control-limits' },
    { label: 'PPAP等级', path: '/quality/ppap/levels' },
    { label: 'PPAP提交', path: '/quality/ppap/submissions' },
    { label: 'PPAP要素', path: '/quality/ppap/elements' },
    { label: 'FMEA管理', path: '/quality/fmea' },
  ];

  for (const { label, path } of pages) {
    test(`${label} 页面加载`, async ({ page }) => {
      await page.locator('.nav-item.parent', { hasText: '品质管理' }).click();
      await page.waitForTimeout(300);
      await page.locator('.nav-item.sub', { hasText: label }).click();
      await page.waitForURL(`**${path}**`, { timeout: 10000 });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `screenshots/quality-${label}.png`, fullPage: true });
    });
  }
});

test.describe('能碳管理 (admin)', () => {
  test.beforeEach(async ({ page }) => {
    const pwd = PWD_SKIP() as string; if (!pwd) return;
    await loginAs(page, 'sipon.wu@126.com', pwd);
  });

  const pages = [
    { label: '能碳管理', path: '/energy' },
    { label: '用能概况', path: '/energy/overview' },
    { label: '能耗分析', path: '/energy/analysis' },
    { label: '碳管理', path: '/energy/carbon' },
  ];

  for (const { label, path } of pages) {
    test(`${label} 页面加载`, async ({ page }) => {
      await page.locator('.nav-item.parent', { hasText: '能碳管理' }).click();
      await page.waitForTimeout(300);
      await page.locator('.nav-item.sub', { hasText: label }).click();
      await page.waitForURL(`**${path}**`, { timeout: 10000 });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `screenshots/energy-${label}.png`, fullPage: true });
    });
  }
});
