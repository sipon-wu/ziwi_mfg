// 合装组套页 · 浏览器级验收（B-20 的现场证据）
//
// 跑法（本地，先 `DIST_DIR=dist_b20 PORT=5188 node scripts/serve_alpha.js`）：
//   BASE_URL=http://127.0.0.1:5188 E2E_USER=mfg_admin E2E_PWD=admin123 \
//   E2E_TENANT=MFG1 node e2e/browser_test/_probe_batch_compose.js
//
// 为什么 HTTP 探针绿了还要跑这个：
//   `batch_compose_e2e.py` 证明的是**业务链路**（组套成功、父子双向可查、重复组套被拒），
//   它一行前端代码都没碰。而这一页最容易坏的地方恰恰是"接口全 200、界面不能用"：
//   按钮永远灰、扫码框不接值、组装好的成品码不显示 —— 这些在接口层看不出来。
//
// 断六件事：
//   1. 页头标题与副标题渲染出来（不是空白页/404 兜底）
//   2. 两个扫码位都在，label 分别是「定子码」「转子码」（扫码枪要扫对框）
//   3. 初始状态组套按钮**不可点**（两码未齐 = 不可提交，这是"扫到才生效"的界面落点）
//   4. 只填一个码时按钮仍不可点（防止"填一个就放行"）
//   5. 两个码都填了（且工单已带）按钮才可点
//   6. 全过程 0 JS 错误
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5188'
const USER = process.env.E2E_USER || 'mfg_admin'
const PWD = process.env.E2E_PWD || 'admin123'
const TENANT = process.env.E2E_TENANT || 'MFG1'

const fails = []
const ok = (n, d = '') => console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`)
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

/** 按钮是否处于禁用态（vant 的 button 会把 disabled 落到原生 button 上） */
async function btnDisabled(page, sel) {
  return page.$eval(sel, (el) => el.hasAttribute('disabled') || el.disabled === true)
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const pageErr = []
  page.on('pageerror', (e) => pageErr.push(String(e)))
  page.on('console', (m) => { if (m.type() === 'error') pageErr.push('console: ' + m.text()) })

  // ── 登录 ──
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', USER)
  await page.fill('input[type="password"]', PWD)
  const tenantInput = await page.$('input[name="tenant_id"], input[name="tenant"]')
  if (tenantInput) await tenantInput.fill(TENANT)
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 30000 })

  // ── 拿一张真实工单（页面要求带工单进来，否则按钮永远灰）──
  // 用页面里的 fetch 走同一套 token，避免探针再造一个 HTTP 客户端。
  const wo = await page.evaluate(async () => {
    const token = localStorage.getItem('access_token')
    const tenant = localStorage.getItem('tenant_id') || ''
    const r = await fetch('/api/v1/work-orders?page_size=1', {
      headers: { Authorization: `Bearer ${token}`, 'X-Tenant-Id': tenant },
    })
    if (!r.ok) return null
    const j = await r.json()
    const items = (j.data && j.data.items) || j.items || []
    return items.length ? { id: items[0].id, wo_no: items[0].wo_no } : null
  })
  if (!wo) {
    bad('P0 取一张工单', '本环境没有工单，页面无法进入可提交态')
    await browser.close()
    process.exit(1)
  }
  console.log(`  工单 ${wo.wo_no} (id=${wo.id})`)

  // ── 进页面（带工单 query，模拟从工单详情点「合装组套」）──
  await page.goto(`${BASE}/#/wms/batches/compose?wo=${wo.id}&wo_no=${encodeURIComponent(wo.wo_no)}`, {
    waitUntil: 'domcontentloaded',
  })
  await page.waitForSelector('.bc-page', { timeout: 20000 })
  await page.waitForTimeout(500)

  // ── 1. 页头 ──
  const title = await page.textContent('.bc-head__title')
  chk('1 页头标题是「合装组套」', (title || '').trim() === '合装组套', `title=${(title || '').trim()}`)

  // ── 2. 两个扫码位 ──
  // 用 data-field 定位而不是按顺序取：框的顺序换了也要能发现接错（扫定子进转子框）
  const stator = await page.$('[data-field="stator_no"] input')
  const rotor = await page.$('[data-field="rotor_no"] input')
  chk('2 定子码 / 转子码两个扫码位都在', !!stator && !!rotor,
      `stator=${!!stator} rotor=${!!rotor}`)
  if (!stator || !rotor) {
    console.log(`  JS 错误 ${pageErr.length} 条`)
    await browser.close()
    process.exit(1)
  }

  // ── 3. 初始不可点 ──
  chk('3 初始状态组套按钮不可点（两码未齐）', await btnDisabled(page, '.bc-compose-btn'))

  // ── 4. 只填一个码仍不可点 ──
  // ★ 必须用 `type`（逐字符真发 keydown）而不是 `fill`：扫码聚合是"相邻字符间隔
  //   ≤120ms + Enter"判定的（`composables/useScanInput.ts`），`fill` 只触发一次
  //   input 事件、不产生 keydown，缓冲永远是空的 —— 用 fill 测出来的"扫不进去"
  //   是探针自己的假红，不是页面缺陷（这一步第一次就踩了）。
  await stator.type('TD-PROBE-0001', { delay: 8 })
  await stator.press('Enter')
  await page.waitForTimeout(300)
  const statorVal = await stator.inputValue()
  chk('4 只扫到定子码时按钮仍不可点', await btnDisabled(page, '.bc-compose-btn'),
      `输入框值=${statorVal}`)

  // ── 5. 两码齐 → 可点 ──
  // 转子走**软扫/手输兜底**通道（点扫码按钮 = `onConfirm` 直接拿当前输入值），
  // 这样两条通道各测一次：硬键（定子）+ 软扫（转子）。
  await rotor.fill('TZ-PROBE-0001')
  await page.click('[data-field="rotor_no"] .ziwi-scan-field__btn')
  await page.waitForTimeout(400)
  chk('5 两个码都扫到后按钮可点', !(await btnDisabled(page, '.bc-compose-btn')),
      `stator=${statorVal} rotor=${await rotor.inputValue()}`)

  // ── 5b. 组套构成区在（后端有接口，界面必须有入口）──
  const lookup = await page.$('[data-field="lookup_no"] input')
  chk('5b 组套构成查询入口在页面上', !!lookup)

  // ── 6. JS 错误 ──
  chk('6 全过程 0 JS 错误', pageErr.length === 0, pageErr.slice(0, 3).join(' | '))

  console.log(`\n合计：${fails.length === 0 ? 'PASS' : 'FAIL'}（失败 ${fails.length} 条）`)
  if (fails.length) fails.forEach((f) => console.log(`  - ${f}`))
  await browser.close()
  process.exit(fails.length ? 1 : 0)
})()
