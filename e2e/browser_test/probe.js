// probe.js - 探测 mfg1 真实状态：API 探针 + UI 探查（登录/菜单/选择器/截图）
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'https://mfg1.ziwi.cn';
const API = 'https://mfg1.ziwi.cn/api/v1';
const SHOT_DIR = path.join(__dirname, 'screenshots');
if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

const log = (...a) => console.log(...a);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function apiProbe() {
  log('\n===== [API 探针] =====');
  const results = {};

  // 1) health
  try {
    const r = await fetch(`${API}/health`, { method: 'GET' });
    results.health = { status: r.status, body: (await r.text()).slice(0, 200) };
  } catch (e) { results.health = { error: String(e).slice(0, 200) }; }

  // 2) login
  let token = null;
  try {
    const r = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'test_admin', password: 'test123456', tenant: 'mfg_demo' })
    });
    const j = await r.json();
    results.login = { status: r.status, code: j.code, msg: j.message, hasToken: !!(j.data && j.data.token) };
    if (j.data && j.data.token) token = j.data.token;
    if (!token && j.data && j.data.access_token) token = j.data.access_token;
  } catch (e) { results.login = { error: String(e).slice(0, 200) }; }

  const auth = token ? { 'Authorization': `Bearer ${token}` } : {};
  const get = async (url) => {
    try {
      const r = await fetch(`${API}${url}`, { headers: { 'Content-Type': 'application/json', ...auth } });
      let body = '';
      try { body = (await r.json()); body = JSON.stringify(body).slice(0, 300); } catch { body = (await r.text()).slice(0, 300); }
      return { status: r.status, body };
    } catch (e) { return { error: String(e).slice(0, 200) }; }
  };

  // 3) 已知 5 个阻断端点
  results['GET /wms/reports/stock-summary'] = await get('/wms/reports/stock-summary');
  results['GET /wms/receipt-orders'] = await get('/wms/receipt-orders');
  results['GET /wms/issue-orders'] = await get('/wms/issue-orders');

  // 探测一些常见模块入口
  for (const ep of ['/factories', '/plants', '/materials', '/warehouses', '/suppliers', '/customers', '/boms', '/purchase-orders', '/sales-orders', '/work-orders', '/inventory', '/inventory-transactions', '/inspections', '/dashboard']) {
    results[`GET ${ep}`] = await get(ep);
  }

  log(JSON.stringify(results, null, 2));
  fs.writeFileSync(path.join(__dirname, 'probe_api.json'), JSON.stringify(results, null, 2));
  return { token, results };
}

async function uiExplore(token) {
  log('\n===== [UI 探查] =====');
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleMsgs = [];
  const failedReqs = [];
  page.on('console', m => consoleMsgs.push(`[${m.type()}] ${m.text()}`));
  page.on('pageerror', e => consoleMsgs.push(`[pageerror] ${e.message}`));
  page.on('requestfailed', r => failedReqs.push(`${r.method()} ${r.url()} :: ${r.failure() ? r.failure().errorText : ''}`));

  const out = { url: null, title: null, htmlLen: 0, menuText: '', formFields: [], console: consoleMsgs, failedReqs };

  try {
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 30000 });
  } catch (e) { log('goto error:', String(e).slice(0, 200)); }

  await sleep(1500);
  out.url = page.url();
  out.title = await page.title();
  out.htmlLen = (await page.content()).length;
  await page.screenshot({ path: path.join(SHOT_DIR, '01_home.png'), fullPage: false });
  log('首页 url=', out.url, 'title=', out.title, 'htmlLen=', out.htmlLen);

  // 尝试识别登录表单
  const inputs = await page.$$eval('input', els => els.map(e => ({ type: e.type, name: e.name, id: e.id, placeholder: e.placeholder, autocomplete: e.autocomplete })));
  out.formFields = inputs;
  log('input 字段:', JSON.stringify(inputs));

  // 尝试填写登录（多策略）
  const fillLogin = async () => {
    // 用户名
    for (const sel of ['input[name="username"]', 'input[name="account"]', 'input[type="text"]', '#username', 'input[autocomplete="username"]', 'input[placeholder*="用户" i]', 'input[placeholder*="账号" i]']) {
      const el = await page.$(sel);
      if (el) { await el.fill('test_admin'); log('填用户名 via', sel); break; }
    }
    // 密码
    for (const sel of ['input[name="password"]', 'input[type="password"]', '#password', 'input[autocomplete="current-password"]', 'input[placeholder*="密码" i]']) {
      const el = await page.$(sel);
      if (el) { await el.fill('test123456'); log('填密码 via', sel); break; }
    }
    // 租户（如有）
    for (const sel of ['input[name="tenant"]', 'input[name="tenant_id"]', 'input[placeholder*="租户" i]']) {
      const el = await page.$(sel);
      if (el) { await el.fill('mfg_demo'); log('填租户 via', sel); break; }
    }
  };

  await fillLogin();
  await page.screenshot({ path: path.join(SHOT_DIR, '02_login_filled.png'), fullPage: false });

  // 提交：点击按钮
  let submitted = false;
  for (const sel of ['button[type="submit"]', 'button:has-text("登录")', 'button:has-text("Login")', 'button:has-text("登 录")', 'input[type="submit"]', '.login-btn', '#loginBtn']) {
    const el = await page.$(sel);
    if (el) { await el.click(); submitted = true; log('点击提交 via', sel); break; }
  }
  if (!submitted) { log('未找到提交按钮，尝试回车'); await page.keyboard.press('Enter'); }
  await sleep(3000);
  await page.screenshot({ path: path.join(SHOT_DIR, '03_after_login.png'), fullPage: false });
  out.urlAfterLogin = page.url();
  out.titleAfterLogin = await page.title();
  log('登录后 url=', out.urlAfterLogin, 'title=', out.titleAfterLogin);

  // 提取菜单文本与链接
  const navInfo = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('a, [role="menuitem"], .menu-item, li')).map(e => ({
      text: (e.textContent || '').trim().slice(0, 40),
      href: e.href || ''
    })).filter(x => x.text && x.text.length > 0);
    return { bodyText: document.body.innerText.slice(0, 1500), links: links.slice(0, 80) };
  });
  out.menuText = navInfo.bodyText;
  out.navLinks = navInfo.links;
  log('--- 页面可见文本(前1500) ---');
  log(navInfo.bodyText);
  log('--- 导航链接 ---');
  log(JSON.stringify(navInfo.links, null, 2));

  // 记录所有路由类链接（href 含路径）
  const hrefs = navInfo.links.map(l => l.href).filter(h => h && h.includes(BASE));
  out.appRoutes = [...new Set(hrefs)];
  log('应用内路由:', JSON.stringify(out.appRoutes, null, 2));

  out.console = consoleMsgs;
  out.failedReqs = failedReqs;
  fs.writeFileSync(path.join(__dirname, 'probe_ui.json'), JSON.stringify(out, null, 2));
  log('\n[控制台消息]', JSON.stringify(consoleMsgs, null, 2));
  log('\n[失败请求]', JSON.stringify(failedReqs, null, 2));

  await browser.close();
}

(async () => {
  try {
    const { token, results } = await apiProbe();
    await uiExplore(token);
    log('\n探测完成。结果已写入 probe_api.json / probe_ui.json');
  } catch (e) {
    log('探针致命错误:', e);
  }
})();
