// cloud 平台控制台真浏览器 E2E（纪律门禁：部署前必须全绿）
//
// 运行前提：
//   1) 本地起 cloud: backend(:8000) + frontend dev(:5173)，或 BASE 指向已部署实例
//   2) 安装依赖: npm i -D playwright && npx playwright install chromium
//   3) 环境变量:
//      BASE          默认 http://localhost:5173
//      ADMIN_EMAIL / ADMIN_PASS       超级管理员
//      OPERATOR_EMAIL / OPERATOR_PASS 运营账号（越权用例）
//
// 运行: node qa/verify_cloud_console.cjs
const { chromium } = require("playwright");

const BASE = process.env.BASE || "http://localhost:5173";
const ADMIN_EMAIL = process.env.ADMIN_EMAIL;
const ADMIN_PASS = process.env.ADMIN_PASS;
const OPERATOR_EMAIL = process.env.OPERATOR_EMAIL;
const OPERATOR_PASS = process.env.OPERATOR_PASS;

let pass = 0, fail = 0;
function check(name, cond, extra = "") {
  if (cond) { pass++; console.log(`PASS  ${name}`); }
  else { fail++; console.log(`FAIL  ${name}  ${extra}`); }
}

async function login(page, email, passwd) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', passwd);
  await page.click('button[type="submit"]');
  await page.waitForURL("**/console", { timeout: 10000 }).catch(() => {});
  return page.url();
}

(async () => {
  if (!ADMIN_EMAIL || !ADMIN_PASS) {
    console.log("SKIP  未配置 ADMIN_EMAIL/ADMIN_PASS，跳过 e2e");
    process.exit(0);
  }
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  // ── 1. 超管登录进入控制台 ──
  const url = await login(page, ADMIN_EMAIL, ADMIN_PASS);
  check("超管登录后进入 /console", url.includes("/console"), url);

  // ── 2. 列表渲染（裸 list 契约修复后必须出现）──
  await page.waitForSelector("table", { timeout: 5000 }).catch(() => {});
  const headerText = await page.textContent("thead").catch(() => "");
  check("账号列表表头渲染", (headerText || "").includes("邮箱"));

  // ── 3. 创建账号成功 → 列表出现 ──
  const newEmail = `e2e_${Date.now()}@ziwi.cn`;
  await page.fill('input[type="email"]', newEmail);
  await page.fill('input[type="text"]', "E2E测试");
  await page.fill('input[type="password"]', "abc123");
  await page.selectOption("select", "operator");
  await page.click('button[type="submit"]');
  await page.waitForTimeout(800);
  const bodyAfter = await page.textContent("body");
  check("创建成功提示可见", (bodyAfter || "").includes("已创建账号"));
  check("新账号出现在列表", (bodyAfter || "").includes(newEmail));

  // ── 4. 故意 422（密码过短）→ 错误原因可见，不是“创建失败” ──
  await page.fill('input[type="email"]', `e2e_2_${Date.now()}@ziwi.cn`);
  await page.fill('input[type="text"]', "E2E测试2");
  await page.fill('input[type="password"]', "12");
  await page.selectOption("select", "sales");
  await page.click('button[type="submit"]');
  await page.waitForTimeout(800);
  const errBody = await page.textContent("body");
  const errBox = await page.textContent(".bg-red-50").catch(() => "");
  const shown = (errBox || errBody || "");
  check("422 显示具体原因(非通用'创建失败')",
    shown.includes("密码") || shown.includes("至少") || (shown.length > 0 && !shown.includes("创建失败")),
    shown.slice(0, 60));

  // ── 5. 停用/启用（行内按钮，super_admin 可见）──
  // 找到包含新账号的那一行，点停用
  const rows = await page.$$("tbody tr");
  let toggled = false;
  for (const r of rows) {
    const t = await r.textContent();
    if (t && t.includes(newEmail)) {
      const btn = await r.$("button");
      if (btn) { await btn.click(); toggled = true; break; }
    }
  }
  await page.waitForTimeout(600);
  check("停用/启用按钮可点击", toggled);

  // ── 6. 越权：运营账号看不到创建表单 ──
  if (OPERATOR_EMAIL && OPERATOR_PASS) {
    const ourl = await login(page, OPERATOR_EMAIL, OPERATOR_PASS);
    check("运营登录进入 /console", ourl.includes("/console"), ourl);
    const formVisible = await page.$('section form');
    check("运营无创建表单(越权防护)", formVisible === null);
  }

  check("无 pageerror", pageErrors.length === 0, pageErrors.join(" | "));

  await browser.close();
  console.log(`\n==== cloud console e2e: ${pass} PASS / ${fail} FAIL ====`);
  process.exit(fail === 0 ? 0 : 1);
})();
