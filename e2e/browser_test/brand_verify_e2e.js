// brand_verify_e2e.js - 品牌改名「知微智造」线上四点位真浏览器验证
//
// 覆盖四个品牌串展示位（都是构建时打进产物、HTTP 层已验证过，这里验"浏览器渲染后
// 用户实际看到的是什么"）：
//   B1 <title>            index.html
//   B2 登录页品牌名        Login.vue  .login-brand
//   B3 侧边栏 logo 标题    MainLayout.vue  .logo-title
//   B4 顶栏标题            MainLayout.vue  .top-title
//   B5 车间大屏 H1         WorkshopScreen.vue  /workshop
//
// 用法：BASE_URL=https://mfg1.ziwi.cn node brand_verify_e2e.js
//       E2E_USER / E2E_PASSWORD / E2E_TENANT 可覆盖凭据
//     （不用裸 USERNAME：Windows 有同名内置环境变量会顶掉默认值）
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = (process.env.BASE_URL || 'https://mfg1.ziwi.cn').replace(/\/$/, '');
const USER = process.env.E2E_USER || 'mfg_admin';
const PASS = process.env.E2E_PASSWORD || 'admin123';
const TENANT = process.env.E2E_TENANT || 'mfg_demo';

const NEW = '知微智造';
const OLD = '知微制造';

const SHOT_DIR = path.join(__dirname, 'screenshots', 'brand_verify');
if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

const results = [];
function check(id, label, actual, expect) {
  const pass = String(actual) === String(expect);
  results.push({ id, label, pass, expect, actual: String(actual) });
  console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${id} ${label}  expect="${expect}" actual="${actual}"`);
  return pass;
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();

  try {
    // ---------- B1 + B2 登录页 ----------
    console.log('\n===== 登录页 =====');
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('.login-brand', { timeout: 20000 });
    check('B1', '<title>', await page.title(), `${NEW} · ziwi`);
    check('B2', '登录页品牌名', (await page.locator('.login-brand').innerText()).trim(), NEW);
    await page.screenshot({ path: path.join(SHOT_DIR, 'B1B2_login.png') });

    // 整页文本里不应再出现旧名（防漏点：某个角落还写死旧名）
    const loginText = await page.locator('body').innerText();
    check('B2b', '登录页无旧名残留', loginText.includes(OLD) ? `含"${OLD}"` : '无', '无');

    // ---------- 登录 ----------
    console.log('\n===== 登录 =====');
    await page.fill('input[type="text"], input[name="username"], input[placeholder*="用户名"]', USER);
    await page.fill('input[type="password"]', PASS);
    // 租户选择器：Vant picker，可能不是必填；有就点确定
    await page.locator('button[type="submit"]').click();
    // 不能写死 sleep：staging 实测登录 200 后还要拉权限/菜单
    await page.waitForURL(u => !u.toString().includes('login'), { timeout: 25000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const url = page.url();
    console.log(`  登录后 URL: ${url}`);
    if (url.includes('login')) throw new Error('登录未跳转，仍停在登录页');

    // ---------- B3 + B4 侧边栏 / 顶栏 ----------
    console.log('\n===== 布局品牌元素 =====');
    await page.waitForSelector('.logo-title', { timeout: 20000 });
    check('B3', '侧边栏 logo 标题', (await page.locator('.logo-title').innerText()).trim(), NEW);
    check('B4', '顶栏标题', (await page.locator('.top-title').innerText()).trim(), `${NEW}管理系统`);
    await page.screenshot({ path: path.join(SHOT_DIR, 'B3B4_layout.png') });

    // ---------- B5 车间大屏 ----------
    console.log('\n===== 车间大屏 =====');
    await page.goto(BASE + '/#/workshop', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(3000);
    const h1 = await page.locator('h1').first().innerText().catch(() => '');
    check('B5', '车间大屏 H1', h1.trim(), `${NEW} · 车间大屏`);
    await page.screenshot({ path: path.join(SHOT_DIR, 'B5_workshop.png') });

    // ---------- 汇总 ----------
    const fails = results.filter(r => !r.pass);
    console.log('\n===== 汇总 =====');
    console.log(`${results.length - fails.length}/${results.length} 通过`);
    if (fails.length) {
      console.log('失败项：');
      fails.forEach(f => console.log(`  - ${f.id} ${f.label}: expect="${f.expect}" actual="${f.actual}"`));
    }
    fs.writeFileSync(
      path.join(__dirname, 'brand_verify_result.json'),
      JSON.stringify({ base: BASE, at: new Date().toISOString(), results }, null, 2)
    );
    await browser.close();
    process.exit(fails.length ? 1 : 0);
  } catch (e) {
    console.error('\n[FATAL]', e.message);
    await page.screenshot({ path: path.join(SHOT_DIR, 'FATAL.png') }).catch(() => {});
    await browser.close();
    process.exit(2);
  }
})();
