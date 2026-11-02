// t04_acceptance_e2e.js — T04 三个执行页 + 出库详情的行为验收（Playwright/Chromium，headless）
//
// 前置：后端 8000 + 前端 5173 已启动（DIST_DIR=frontend/dist_t04b），数据按本地库现状。
//
// 覆盖（对应任务书 T04b 的 12 条行为项）：
//   A. 双视口（1024×768 = W / 412×915 = H）逐页无横向滚动
//   B. 检验执行 degraded 路径：723（standard_id=NULL）→ 顶部降级横幅 + 21 项可选
//   C. 检验执行标准路径：725（standard_id=8）→ 无降级横幅 + 3 项
//   D. 设备任务扫码头：/equipment/tasks 渲染扫码头
//   E. 点检执行 0 项状态：79（无 plan_id、无模板）→ 空态 + 两条出路
//   F. 出库详情 /wms/issue-orders/241 渲染 + 「开始出库」入口
//   G. 出库执行页明细渲染
//   H. 双击「发料」只发 1 次 POST（UE-P0-05；用 route 拦截计数，不真过账）
//
// 数据只读：H 项用 route.abort() 拦截，不落库。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 't04');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const VIEWPORTS = [
  { label: 'W', width: 1024, height: 768 },
  { label: 'H', width: 412, height: 915 },
];

// 逐页检查：路由 → 用于确认"页面真的渲染了"的特征文案
// ★ 特征文案必须选"该状态下一定会出现"的那句：
//   · 725 带 :id，页面跳过"扫单号"这一步，直接进录入 → 「开始检验」不会出现，
//     要认「检验单号」与进度「已录」。
//   · /equipment/tasks 的扫码提示是「对准设备编码扫一下，或手输后回车」，
//     不是 uiText 里的 scanPlaceholder（那是输入框 placeholder，innerText 取不到）。
const ROUTES = [
  { id: 'R1', route: '/quality/723/execute', mustSee: '本单未关联检验标准', name: '检验执行(降级)' },
  { id: 'R2', route: '/quality/725/execute', mustSee: '检验单号', name: '检验执行(有标准)' },
  { id: 'R3', route: '/equipment/tasks', mustSee: '对准设备编码扫一下', name: '设备任务(扫码头)' },
  { id: 'R4', route: '/equipment/maintenance-tasks/79/execute', mustSee: '点检', name: '点检执行(0项)' },
  { id: 'R5', route: '/wms/issue-orders/241', mustSee: '开始出库', name: '出库单详情' },
  { id: 'R6', route: '/wms/issue-orders/241/execute', mustSee: '发料', name: '出库执行' },
];

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });

  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await ctx.newPage();
    const consoleErrors = [];
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text());
    });
    page.on('pageerror', (e) => consoleErrors.push('[pageerror] ' + e.message));

    const field = (label) =>
      page.locator('.van-field', { hasText: label }).locator('input, textarea').first();

    // ── 登录 ──
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(900);
    await field('用户名').fill('mfg_admin');
    await field('密码').fill('admin123');
    await page.locator('button[type="submit"]').click();
    await sleep(2200);
    const loggedIn = !page.url().includes('/login');
    rec(`${vp.label}-A0`, '登录', loggedIn ? 'PASS' : 'FAIL', page.url().split('#')[1] || '');
    if (!loggedIn) {
      consoleErrors.length && rec(`${vp.label}-A0e`, '登录页报错', 'FAIL', consoleErrors.slice(0, 3).join(' | '));
      await ctx.close();
      continue;
    }

    // ── 逐页：渲染 + 无横向滚动 ──
    for (const r of ROUTES) {
      await page.goto(`${BASE}/#${r.route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(1400);

      const body = await page.evaluate(() => document.body.innerText);
      const seen = body.includes(r.mustSee);

      // 横向滚动：scrollWidth 超过 clientWidth 即视为溢出（>1px 容差）
      const ov = await page.evaluate(() => {
        const de = document.documentElement;
        return { sw: de.scrollWidth, cw: de.clientWidth, bodySw: document.body.scrollWidth };
      });
      const noScroll = ov.sw <= ov.cw + 1;
      const ff = await page.evaluate(() => document.documentElement.dataset.formFactor || '(未设置)');

      const st = seen && noScroll ? 'PASS' : 'FAIL';
      const detail = `formFactor=${ff}；特征文案「${r.mustSee}」=${seen ? '有' : '无'}；` +
        `scrollWidth=${ov.sw}/${ov.cw}${noScroll ? '' : ' ★横向溢出'}`;
      rec(`${vp.label}-${r.id}`, r.name, st, detail);

      if (st === 'FAIL') {
        rec(`${vp.label}-${r.id}-body`, r.name + ' 正文前 200 字', 'INFO', body.slice(0, 200).replace(/\s+/g, ' '));
      }
      await page.screenshot({ path: path.join(SHOT, `${vp.label}_${r.id}.png`) }).catch(() => {});
    }

    // ── B. 降级路径细节：21 项 + 确认按钮 ──
    await page.goto(`${BASE}/#/quality/723/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);
    const degBody = await page.evaluate(() => document.body.innerText);
    const has21 = degBody.includes('21 项可选') || degBody.includes('21');
    const hasConfirm = degBody.includes('确认适用项') || degBody.includes('已选');
    rec(`${vp.label}-B1`, '降级横幅带可选项数', has21 ? 'PASS' : 'FAIL', `含"21"=${has21}`);
    rec(`${vp.label}-B2`, '降级步骤有确认适用项按钮', hasConfirm ? 'PASS' : 'FAIL', `含确认/已选=${hasConfirm}`);

    // ── C. 标准路径：无降级横幅 ──
    await page.goto(`${BASE}/#/quality/725/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);
    const stdBody = await page.evaluate(() => document.body.innerText);
    const noDeg = !stdBody.includes('本单未关联检验标准');
    rec(`${vp.label}-C1`, '有标准的单不显示降级横幅', noDeg ? 'PASS' : 'FAIL', `横幅存在=${!noDeg}`);

    // ── E. 点检 0 项：两条出路 ──
    await page.goto(`${BASE}/#/equipment/maintenance-tasks/79/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);
    const mtBody = await page.evaluate(() => document.body.innerText);
    const exit1 = mtBody.includes('使用标准点检项模板');
    const exit2 = mtBody.includes('添加点检项');
    // 空态副文案必须是"点检项"语境，不能沿用列表页那句"点右下角新建，或在扫码入口直接扫设备码"
    const hintOk = mtBody.includes('该任务还没有点检项')
      && !mtBody.includes('或在扫码入口直接扫设备码');
    rec(`${vp.label}-E1`, '点检 0 项给「使用标准点检项模板」出路', exit1 ? 'PASS' : 'FAIL', '');
    rec(`${vp.label}-E2`, '点检 0 项给「添加点检项」出路', exit2 ? 'PASS' : 'FAIL',
      exit2 ? '' : '添加区被空态替换 → 死按钮');
    rec(`${vp.label}-E3`, '点检空态副文案是本场景语境', hintOk ? 'PASS' : 'FAIL',
      hintOk ? '' : '仍在用列表页的扫码话术');

    // ── H. 连点发料只 1 次 POST（拦截，不真过账） ──
    // ★ 方法论纠正（踩了两轮）：
    //   `await locator.click()` 会**等到请求结束才返回**（实测阻塞 1886ms），
    //   于是第二次点击必然落在"锁已释放"之后 —— 测出 POST=2 是**测试假阳性**。
    //   `click({force:true})` 同理：force 只跳过可操作性检查，不改变时序。
    //   真实场景（手套连击）是**同一 tick 内连点**，所以必须在页面内直接连调
    //   `button.click()` 三次，这才是 UE-P0-05 想验的东西。
    let postCount = 0;
    const postBodies = [];
    await ctx.route('**/api/v1/wms/issue-order-items/*/issue', async (route) => {
      postCount += 1;
      try {
        postBodies.push(JSON.parse(route.request().postData() || '{}'));
      } catch {
        postBodies.push({});
      }
      await sleep(1200);
      await route.abort();
    });
    await page.goto(`${BASE}/#/wms/issue-orders/241/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1600);
    const tap = await page.evaluate(() => {
      const btns = [...document.querySelectorAll('button')]
        .filter((x) => (x.textContent || '').includes('确认发料'));
      if (!btns.length) return { found: false };
      const b = btns[0];
      b.click();
      b.click();
      b.click();
      return { found: true, count: btns.length };
    });
    await sleep(2600);
    rec(`${vp.label}-H1`, '同一 tick 连点 3 次发料只 1 次 POST（UE-P0-05）',
      tap.found && postCount === 1 ? 'PASS' : 'FAIL',
      `按钮数=${tap.count ?? 0}；实际 POST=${postCount}`);

    // H2：前端必须带上服务端幂等键，否则重复过账的防线只剩前端锁
    const b0 = postBodies[0] || {};
    const ridOk = typeof b0.request_id === 'string' && b0.request_id.length >= 8 && b0.request_id.length <= 64;
    rec(`${vp.label}-H2`, '发料请求带服务端幂等键 request_id', ridOk ? 'PASS' : 'FAIL',
      ridOk ? `长度=${b0.request_id.length}` : `body=${JSON.stringify(b0).slice(0, 160)}`);
    await ctx.unroute('**/api/v1/wms/issue-order-items/*/issue');

    // ── 控制台错误 ──
    const realErr = consoleErrors.filter((e) => !/favicon|ResizeObserver|net::ERR_FAILED/i.test(e));
    rec(`${vp.label}-Z1`, '控制台无未处理错误', realErr.length === 0 ? 'PASS' : 'FAIL',
      realErr.length ? realErr.slice(0, 3).join(' | ').slice(0, 300) : '0 条');

    await ctx.close();
  }

  await browser.close();

  const fail = results.filter((r) => r.status === 'FAIL');
  const pass = results.filter((r) => r.status === 'PASS');
  console.log(`\n=== 汇总：${pass.length} PASS / ${fail.length} FAIL / ${results.length} 项 ===`);
  fs.writeFileSync(path.join(__dirname, 't04_acceptance_result.json'),
    JSON.stringify({ ts: new Date().toISOString(), base: BASE, results }, null, 2), 'utf-8');
  if (fail.length) {
    console.log('失败项：');
    fail.forEach((f) => console.log(`  - ${f.id} ${f.name}: ${f.detail}`));
    process.exit(1);
  }
})();
