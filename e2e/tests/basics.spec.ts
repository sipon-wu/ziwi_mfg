/**
 * mfg1 E2E 测试 —— 基础数据模块
 *
 * 测试：工序定义/工作中心/工艺路线/产品管理/工厂日历的页面加载
 */
import { test, expect } from '@playwright/test';
import { loginAs } from '../utils/login';

const BASE_URLS = [
  { path: '/basics/operations', label: '工序定义' },
  { path: '/basics/work-centers', label: '工作中心' },
  { path: '/basics/routes', label: '工艺路线' },
  { path: '/basics/products', label: '产品管理' },
  { path: '/basics/calendar', label: '工厂日历' },
];

test.describe('基础数据 (admin)', () => {
  test.beforeEach(async ({ page }) => {
    const pwd = process.env.CLOUD_PASSWORD;
    if (!pwd) { test.skip(true, '未设置 CLOUD_PASSWORD'); return; }
    await loginAs(page, 'sipon.wu@126.com', pwd);
  });

  for (const { path, label } of BASE_URLS) {
    test(`${label} 页面加载无错误`, async ({ page }) => {
      const errors: string[] = [];
      page.on('requestfailed', (req) => errors.push(`${req.url()} — ${req.failure()?.errorText}`));
      page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`[CONSOLE] ${msg.text()}`); });

      // 通过左侧菜单导航
      await page.locator('.nav-item.parent', { hasText: '基础数据' }).click();
      await page.waitForTimeout(300);
      await page.locator('.nav-item.sub', { hasText: label }).click();
      await page.waitForURL(`**${path}**`, { timeout: 10000 });
      await page.waitForTimeout(1500);

      await page.screenshot({ path: `screenshots/basics-${label}.png`, fullPage: true });

      // 允许 favicon 404
      const realErrors = errors.filter(e => !e.includes('favicon'));
      expect(realErrors).toEqual([]);
    });
  }
});
