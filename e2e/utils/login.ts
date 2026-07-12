import { Page } from '@playwright/test';

/**
 * 本地子账号（本地 bcrypt 认证）配置
 * 所有测试用户统一密码 test123456（由种子数据脚本设定）
 */
export const LOCAL_USERS: Record<string, { username: string; password: string; role: string; label: string }> = {
  admin: { username: 'test_admin', password: 'test123456', role: 'admin', label: '测试系统管理员' },
  mfg_admin: { username: 'mfg_admin', password: 'test123456', role: 'admin', label: 'mfg平台管理员' },
  dept_head: { username: 'test_dept_head', password: 'test123456', role: 'department_head', label: '部门主管' },
  team_leader: { username: 'test_team_leader', password: 'test123456', role: 'team_leader', label: '班组长' },
  scheduler: { username: 'test_scheduler', password: 'test123456', role: 'scheduler', label: '调度员' },
  proc_eng: { username: 'test_proc_eng', password: 'test123456', role: 'process_engineer', label: '工艺工程师' },
  key_user: { username: 'test_key_user', password: 'test123456', role: 'key_user', label: '关键用户' },
  maint_tech: { username: 'test_maint_tech', password: 'test123456', role: 'maintenance_tech', label: '设备维保员' },
  inspector: { username: 'test_inspector', password: 'test123456', role: 'inspector', label: '品质检验员' },
  quality_eng: { username: 'test_quality_eng', password: 'test123456', role: 'quality_engineer', label: '品质工程师' },
};

export interface UserInfo {
  id?: number;
  username: string;
  real_name?: string;
  roles: { code: string; name: string }[];
  tenant_id?: string;
  access_token?: string;
}

export interface PageError {
  url: string;
  status: number;
  method: string;
  type: 'network_error' | 'http_error' | 'console_error';
  message: string;
}

/**
 * 使用 Playwright 页面登录 mfg1.ziwi.cn
 * 支持本地子账号（无 @）和 cloud 管理员（有 @）两种登录方式
 */
export async function loginAs(
  page: Page,
  username: string,
  password: string,
  tenantId?: string
): Promise<UserInfo> {
  await page.goto('https://mfg1.ziwi.cn/login', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  // 填写登录表单
  const usernameInput = page.locator('input[placeholder*="用户名"], input[placeholder*="账号"]');
  const passwordInput = page.locator('input[placeholder*="密码"]');

  await usernameInput.fill(username);
  await passwordInput.fill(password);

  // 点击登录按钮（尝试多个可能的文本）
  const loginBtn = page.locator('button:has-text("登 录"), button:has-text("登录")');
  await loginBtn.click();

  // 等待登录成功
  await page.waitForURL('**/cockpit**', { timeout: 20000 });

  // 获取 localStorage 中的 token 和 user_info
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  const userInfoRaw = await page.evaluate(() => localStorage.getItem('user_info'));

  if (!token) {
    throw new Error(`登录失败: username=${username}, 未获取到 access_token`);
  }

  const userInfo: UserInfo = userInfoRaw ? JSON.parse(userInfoRaw) : { username, roles: [] };
  userInfo.access_token = token;

  return userInfo;
}

/**
 * 监听页面错误（网络请求失败 + HTTP 非 2xx + 控制台错误）
 * 返回监听器移除函数
 */
export function watchPageErrors(page: Page): () => PageError[] {
  const errors: PageError[] = [];

  const onRequestFailed = (req: any) => {
    const url = req.url();
    // 忽略 favicon 和 websocket
    if (url.includes('favicon') || url.includes('sockjs')) return;
    errors.push({
      url,
      status: 0,
      method: req.method(),
      type: 'network_error',
      message: req.failure()?.errorText || '请求失败',
    });
  };

  const onResponse = (res: any) => {
    const url = res.url();
    if (url.includes('favicon') || url.includes('sockjs')) return;
    const status = res.status();
    if (status >= 400) {
      errors.push({
        url,
        status,
        method: res.request().method(),
        type: 'http_error',
        message: `HTTP ${status}`,
      });
    }
  };

  const onConsole = (msg: any) => {
    if (msg.type() === 'error') {
      errors.push({
        url: page.url(),
        status: 0,
        method: '',
        type: 'console_error',
        message: msg.text(),
      });
    }
  };

  page.on('requestfailed', onRequestFailed);
  page.on('response', onResponse);
  page.on('console', onConsole);

  return () => {
    page.removeListener('requestfailed', onRequestFailed);
    page.removeListener('response', onResponse);
    page.removeListener('console', onConsole);
    return errors;
  };
}

export async function screenshotPage(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `screenshots/${name}.png`, fullPage: true });
}
