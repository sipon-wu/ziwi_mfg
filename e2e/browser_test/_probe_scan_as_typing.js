// 扫码 vs 手输 · 判定探针（2026-11-10）
//
// 用户口径：「扫码其实和录入一样，只不过用二维码扫码来录入」。
// 也就是说：输入框里放着一串码，按回车，就该查这个码 —— 无论这串码是
// 扫码枪逐字符敲进来的，还是人手一个一个字打进去的。
//
// 本探针不测"扫得准不准"，只测**三条输入路径在回车时是否等价**：
//
//   A. 慢速手输（150ms/字符，模拟真人） + Enter  → 应查到这个码
//   B. 快速键入（10ms/字符，模拟扫码枪）  + Enter  → 应查到这个码
//   C. 慢速手输 + 点「扫码」按钮           → 应查到这个码
//   D. 手输一个"太短的值"（2 字符，低于 minLength=3）+ Enter → 不提交、也不清空输入框
//   E. 打字中途停顿（模拟边看单边敲）+ Enter → 提交的必须是**完整码**，不能是停顿后的后缀
//      （E 比 A 更要命：A 是"没反应"，E 是"静默查了另一个码"，界面上看不出替换）
//
// 跑法：DIST_DIR=frontend/dist_xxx PORT=5190 node scripts/serve_alpha.js
//       BASE_URL=http://127.0.0.1:5190 node e2e/browser_test/_probe_scan_as_typing.js
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5190'
const API = process.env.API_BASE || 'http://127.0.0.1:8000/api/v1'
const TENANT = process.env.E2E_TENANT || 'MFG1'
const USER = process.env.E2E_USER || 'mfg_admin'
const PWD = process.env.E2E_PWD || 'admin123'

const fails = []
let passed = 0
const ok = (n, d = '') => { passed += 1; console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`) }
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

/** 拿一个真实存在的原料码当靶子 */
async function pickCode() {
  const res = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PWD, tenant_code: TENANT }),
  })
  const tok = (await res.json()).access_token
  const r = await fetch(`${API}/wms/batches?page_size=1&batch_type=raw`, {
    headers: { Authorization: `Bearer ${tok}` },
  })
  const d = (await r.json()).data
  return d.items[0].batch_no
}

async function login(page) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.clear())
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', USER)
  await page.fill('input[type="password"]', PWD)
  const t = await page.$('input[name="tenant_id"], input[name="tenant"]')
  if (t) await t.fill(TENANT)
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })
}

/** 逐个字符真敲（产生完整 keydown 序列，和扫码枪/真人一致），返回实际耗时 */
async function typeChars(locator, text, delay) {
  const t0 = Date.now()
  await locator.click()
  await locator.press('Control+a')
  await locator.press('Delete')
  for (const ch of text) {
    await locator.type(ch, { delay: 0 })
    if (delay) await locator.page().waitForTimeout(delay)
  }
  return Date.now() - t0
}

/** 等「结果区里出现了这个码」，不是等「结果区存在」 */
async function waitLooked(page, code, timeout = 12000) {
  try {
    await page.waitForFunction(
      (c) => {
        const box = document.querySelector('.bc-lookup')
        return !!box && (box.innerText || '').includes(c)
      },
      code, { timeout })
    return true
  } catch { return false }
}

// ★ 必须取「查组套构成」那张卡片里的扫码位（页面上一共 3 个）：定子/转子两个框
//   扫完只是把值塞进变量，不会立刻查询 —— 拿它们测"回车有没有反应"永远测不出来。
//   第三个框扫完直接 `doLookup`，才是「扫码/手输 → 立刻查一次」的真实路径。
const scanField = (page) => page.locator('.ziwi-scan-field').last()
const inputOf = (page) => scanField(page).locator('input').first()

/**
 * 每个用例前把页面回到"没有任何查询结果"的干净态。
 *
 * ★ `page.goto()` 对**只有 hash 变化**的地址不会重新加载，组件实例被复用 ——
 *   于是 `.bc-lookup` 里躺着上一个用例的结果。2026-11-10 实测：E 用例在老代码上
 *   本该红（回车什么都没提交），却因为读到 C 用例残留的结果而报绿 —— **假绿**。
 *   所以先 `reload()` 强制新实例，再等结果区**消失**，不是等它存在。
 */
async function freshPage(page) {
  await page.goto(`${BASE}/#/wms/batches/compose`, { waitUntil: 'domcontentloaded' })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.ziwi-scan-field', { timeout: 15000 })
  await page.waitForFunction(() => !document.querySelector('.bc-lookup'), { timeout: 10000 })
}

;(async () => {
  const code = await pickCode()
  console.log(`靶码：${code}`)

  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  page.on('dialog', (d) => d.dismiss())

  console.log('\n== 准备 ==')
  await login(page)
  await page.goto(`${BASE}/#/wms/batches/compose`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.ziwi-scan-field', { timeout: 15000 })
  ok('P0', '已进入合装组套页')

  // ── A 慢速手输 + Enter（真人手感）──────────────────────────
  console.log('\n== A 慢速手输 + Enter（150ms/字符）==')
  {
    const box = inputOf(page)
    const ms = await typeChars(box, code, 150)
    const shown = await box.inputValue()
    chk('A1', shown === code, `输入框内容 = ${JSON.stringify(shown)}（键入 ${ms}ms，${Math.round(ms / code.length)}ms/字符）`)
    await box.press('Enter')
    await page.waitForTimeout(1200)
    const hit = await waitLooked(page, code, 6000)
    chk('A2', hit, hit ? '回车后查到了这个码（手输与扫码等价）' : '回车后**没有任何查询结果** —— 手输这条路走不通')
  }

  // ── B 快速键入 + Enter（扫码枪手感）────────────────────────
  console.log('\n== B 快速键入 + Enter（10ms/字符，模拟扫码枪）==')
  {
    await freshPage(page)
    const box = inputOf(page)
    const ms = await typeChars(box, code, 10)
    await box.press('Enter')
    await page.waitForTimeout(1200)
    const hit = await waitLooked(page, code, 6000)
    chk('B1', hit, `快速键入 ${ms}ms 后回车 → ${hit ? '查到了' : '没查到'}`)
  }

  // ── C 慢速手输 + 点「扫码」按钮 ────────────────────────────
  console.log('\n== C 慢速手输 + 点「扫码」按钮 ==')
  {
    await freshPage(page)
    const box = inputOf(page)
    await typeChars(box, code, 150)
    await scanField(page).locator('.ziwi-scan-field__btn').click()
    await page.waitForTimeout(1200)
    const hit = await waitLooked(page, code, 6000)
    chk('C1', hit, `点按钮 → ${hit ? '查到了' : '没查到'}（若 A 红 C 绿，说明手输被强迫多点一次）`)
  }

  // ── D 半截码 + Enter（负向：不该静默提交截断值）─────────────
  console.log('\n== D 半截码 + Enter（负向）==')
  {
    await freshPage(page)
    const box = inputOf(page)
    // 组件 minLength=3；取 2 个字符才低于阈值（3 个字符按设计就是要提交的）
    const half = code.slice(-2)
    await typeChars(box, half, 150)
    await box.press('Enter')
    await page.waitForTimeout(1000)
    const shown = await box.inputValue()
    const body = await page.evaluate(() => (document.querySelector('.bc-lookup')?.innerText || ''))
    // 期望：不静默清空；且不把半截码当成品提交成一次"查无此码"的错误弹窗
    const stillThere = shown === half
    chk('D1', stillThere, `半截码「${half}」回车后输入框 = ${JSON.stringify(shown)}（不该被悄悄清掉）`)
    const wrongSubmitted = /不存在|查无|未找到/.test(body)
    chk('D2', !wrongSubmitted, wrongSubmitted ? '把半截码当完整码提交了（查无此码）' : '没有把半截码当成品提交')
  }

  // ── E 中途停顿 + Enter（负向：不能提交后缀）──────────────────
  console.log('\n== E 打字中途停顿 400ms + Enter（负向：不能只提交后缀）==')
  {
    await freshPage(page)
    const box = inputOf(page)
    const cut = Math.max(1, Math.floor(code.length / 2))
    const head = code.slice(0, cut)
    const tail = code.slice(cut)
    // 前半段慢敲 → 停 400ms（远超 maxInterval=120ms）→ 后半段慢敲
    await typeChars(box, head, 150)
    await page.waitForTimeout(400)
    for (const ch of tail) {
      await box.type(ch, { delay: 0 })
      await page.waitForTimeout(150)
    }
    const shown = await box.inputValue()
    chk('E1', shown === code, `停顿后输入框 = ${JSON.stringify(shown)}（应为完整 ${code}）`)
    await box.press('Enter')
    await page.waitForTimeout(1500)
    const hit = await waitLooked(page, code, 6000)
    chk('E2', hit, hit ? '提交的是完整码' : `**没有按完整码提交** —— 很可能把后缀「${tail}」当成了一次扫码`)
  }

  await browser.close()
  console.log(`\n通 ${passed} / 断 ${fails.length}`)
  if (fails.length) { console.log('断点：'); fails.forEach((f) => console.log('  -', f)) }
  process.exit(fails.length ? 1 : 0)
})()
