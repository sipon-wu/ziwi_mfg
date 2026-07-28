const { chromium } = require('playwright');

const BASE = process.env.BASE || 'http://127.0.0.1:5173';
const EMAIL = process.env.ADMIN_EMAIL || 'admin@ziwi.cn';
const PASS = process.env.ADMIN_PASS || 'admin123';

(async () => {
  const results = [];
  const check = (name, cond, extra = '') => {
    results.push({ name, ok: !!cond });
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + name + (extra ? ' ' + extra : ''));
  };

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  try {
    // 1) 登录
    await page.goto(BASE + '/login', { waitUntil: 'networkidle' });
    await page.fill('input[type=email]', EMAIL);
    await page.fill('input[type=password]', PASS);
    await page.click('button:has-text("登录")');
    await page.waitForURL('**/console', { timeout: 15000 });
    check('登录后跳转 /console', true);

    // 2) 看板默认渲染
    await page.waitForSelector('text=平台管理控制台', { timeout: 8000 });
    check('控制台标题渲染', true);
    check('看板 KPI(租户用户)', (await page.locator('text=租户用户').count()) > 0);
    check('Token 购销 区块', (await page.locator('text=Token 购销').count()) > 0);
    check('全量工单统计 区块', (await page.locator('text=全量工单统计').count()) > 0);
    check('临期提醒 区块', (await page.locator('text=临期提醒').count()) > 0);
    check('分时图表 SVG 渲染', (await page.locator('svg polyline').count()) > 0);

    // 3) 移动端底部导航切到 设置
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('button:visible:has-text("设置")').click();
    await page.waitForSelector('input[autocomplete="current-password"]', { timeout: 8000 });
    check('设置页 改密表单 渲染', true);

    const curSel = 'input[autocomplete="current-password"]';
    const newPw = page.locator('input[autocomplete="new-password"]');
    const submitBtn = page.locator('button:has-text("确认修改")');
    // 确定性填表：填后回读校验，避免竞态导致字段未写入
    async function fillPw(cur, n1, n2) {
      await page.fill(curSel, cur);
      await newPw.nth(0).fill(n1);
      await newPw.nth(1).fill(n2);
      const v = await page.inputValue(curSel);
      if (v !== cur) throw new Error('current-password 未正确写入: ' + JSON.stringify(v));
    }

    // 3a) 旧密错误 -> 具体原因
    await fillPw('wrongpass', 'admin123', 'admin123');
    await submitBtn.click();
    await page.waitForSelector('text=原密码错误', { timeout: 8000 });
    check('改密-旧密错误 显示具体原因(不吞错)', true);
    // 等提交按钮复位(3a 异步 saving 收尾)，避免与 3b 竞态
    await submitBtn.waitFor({ state: 'visible' });
    await page.waitForTimeout(200);

    // 3b) 正确改密 -> revoke 强制重登
    await fillPw('admin123', 'admin123', 'admin123');
    await submitBtn.click();
    // 仅 200 成功才会出现该提示，失败(422)则明确暴露而非静默挂起
    await page.waitForSelector('text=密码已修改', { timeout: 8000 });
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 10000 });
    check('改密成功-强制重登跳转 /login', true);

    // 3a 故意发错密码触发 422 属预期(浏览器记为 console error)，排除该有意的 422
    const realErrors = errors.filter((e) => !e.includes('422 (Unprocessable'));
    check('无 pageerror/console error', realErrors.length === 0, realErrors.join(' | ').slice(0, 300));
  } catch (e) {
    check('执行异常', false, e.message);
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log('\n=== STAGE2 E2E: ' + (results.length - failed.length) + '/' + results.length + ' PASS ===');
  process.exit(failed.length ? 1 : 0);
})();
