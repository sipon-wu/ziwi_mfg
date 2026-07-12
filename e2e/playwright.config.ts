import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 120000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'test-report' }],
  ],
  use: {
    baseURL: 'https://mfg1.ziwi.cn',
    headless: true,
    screenshot: 'on',
    trace: 'retain-on-failure',
    actionTimeout: 20000,
    navigationTimeout: 30000,
  },
});
