/**
 * T06b — 热敏贴标前端链路 E2E。
 *
 * ## 验证什么
 *
 * 不是"按钮能点"，而是这条链路上三处容易断的地方：
 *
 * 1. **入口分叉** —— 同一张工单上「打印流转卡」（A4）与「打印贴标」（label80）
 *    必须跳到不同 query 的预览页。两个按钮都跳 `?paper=` 空的话，车间点"贴标"
 *    打出来的是 A4 归档件，纸型不对但没人会当场发现。
 * 2. **纸型回显** —— 预览页标题上必须能看出打开的是哪种纸。凭版面判断太晚，
 *    纸已经打出来了。
 * 3. **缩放警示** —— 标签的二维码模块是 0.5mm 算死的，打印对话框勾了「适合纸张」
 *    就会扫不出来。这句提示必须在**点打印之前**就可见，不能只靠 toast。
 *
 * 用法：
 *   BASE_URL=http://127.0.0.1:5173 \
 *   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
 *   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
 *   node e2e/browser_test/t06b_label_e2e.js
 */
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_BASE || BASE.replace(/\/$/, '') + '/api/v1'
const USER = process.env.E2E_USER || 'mfg_admin'
const PASS = process.env.E2E_PASS || 'admin123'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/t06b_label'

const fs = require('fs')
const path = require('path')
fs.mkdirSync(OUT, { recursive: true })

const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail: detail === undefined ? '' : String(detail) })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail === undefined ? '' : '  — ' + detail}`)
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  const jsErrors = []
  page.on('pageerror', (e) => jsErrors.push(String(e)))

  try {
    // ── 登录 ──────────────────────────────────────────────
    await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="username"], input[placeholder*="账号"], input[type="text"]', USER)
    await page.fill('input[type="password"]', PASS)
    await page.click('button[type="submit"]')
    // admin 实际落点是 #/cockpit 不是 dashboard，等"离开登录页"最稳
    await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })
    check('登录成功', true, page.url())

    // ── 直接打开工单详情（从列表点进去容易撞上分页/筛选残留） ──
    // 不从页面 localStorage 取 token：前端存的键名不固定，取不到会静默变成 null，
    // 表现为"没有工单"这种误导性的失败。改为脚本自己调一次登录接口。
    const loginResp = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: USER, password: PASS, tenant_code: 'AH-THR' }),
    })
    const loginBody = await loginResp.json()
    const tok = loginBody.access_token || (loginBody.data && loginBody.data.access_token)
    check('脚本侧登录取到 token', !!tok, loginResp.status)

    const listResp = await fetch(`${API}/work-orders?page=1&page_size=1`, {
      headers: { Authorization: 'Bearer ' + tok },
    })
    const listBody = await listResp.json()
    const d = listBody.data || listBody
    const wo = d && d.items && d.items[0]
    check('取到一条工单', !!wo, wo && wo.id)
    if (!wo) throw new Error('没有工单可供验证')

    await page.goto(`${BASE}/#/work-orders/${wo.id}`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2500)

    // ── 入口分叉 ─────────────────────────────────────────
    const btnFlow = page.locator('button:has-text("打印流转卡")')
    const btnLabel = page.locator('button:has-text("打印贴标")')
    check('详情页有「打印流转卡」', (await btnFlow.count()) > 0)
    check('详情页有「打印贴标」', (await btnLabel.count()) > 0)
    await page.screenshot({ path: path.join(OUT, 'L1_entry_buttons.png'), fullPage: true })

    // ── 点贴标 → 预览页 ──────────────────────────────────
    await btnLabel.first().click()
    await page.waitForFunction(() => location.hash.includes('/print/preview/'), { timeout: 15000 })
    const hash = page.url()
    check('跳到打印预览页', hash.includes('/print/preview/'), hash)
    check('query 带 paper=label80', hash.includes('paper=label80'), hash)

    // 等 PDF 加载完（iframe 有 src 且有留痕码）
    await page.waitForFunction(
      () => {
        const f = document.querySelector('iframe')
        const sub = document.querySelector('.print-page__sub')
        return !!f && !!f.getAttribute('src') && !!sub && sub.textContent.includes('留痕码')
      },
      { timeout: 30000 },
    )

    const badge = (await page.locator('.print-page__paper').textContent()) || ''
    check('标题回显纸型为「热敏贴标」', badge.includes('热敏贴标'), badge.trim())

    const tip = (await page.locator('.print-page__hint').textContent()) || ''
    check('缩放警示在点打印前可见', tip.includes('实际大小') || tip.includes('100%'), tip.trim())

    const frameSrc = await page.locator('iframe').getAttribute('src')
    check('iframe 指向 blob PDF', !!frameSrc && frameSrc.startsWith('blob:'), (frameSrc || '').slice(0, 24))

    // 取 PDF 头几个字节，确认服务端真的返回了 PDF（不是错误页）
    const head = await page.evaluate(async (src) => {
      const buf = await (await fetch(src)).arrayBuffer()
      return Array.from(new Uint8Array(buf.slice(0, 5))).map((c) => String.fromCharCode(c)).join('')
    }, frameSrc)
    check('PDF 字节头为 %PDF-', head === '%PDF-', head)

    await page.screenshot({ path: path.join(OUT, 'L2_label_preview.png'), fullPage: true })

    // ── A4 对照：同一个单据的另一入口必须是另一种纸 ──────────
    await page.goto(`${BASE}/#/work-orders/${wo.id}`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2000)
    await page.locator('button:has-text("打印流转卡")').first().click()
    await page.waitForFunction(() => location.hash.includes('/print/preview/'), { timeout: 15000 })
    const hashA4 = page.url()
    check('流转卡入口不带 paper（默认 A4）', !hashA4.includes('paper='), hashA4)

    await page.waitForFunction(
      () => !!document.querySelector('.print-page__paper'),
      { timeout: 30000 },
    )
    const badgeA4 = (await page.locator('.print-page__paper').textContent()) || ''
    check('A4 入口回显「A4 归档件」', badgeA4.includes('A4'), badgeA4.trim())

    const tipA4 = (await page.locator('.print-page__hint').count()) > 0
      ? (await page.locator('.print-page__hint').textContent()) || ''
      : ''
    check('A4 不显示标签缩放警示', !tipA4.includes('实际大小'), tipA4.trim() || '(无提示)')

    await page.screenshot({ path: path.join(OUT, 'L3_a4_preview.png'), fullPage: true })

    check('无 JS 运行时错误', jsErrors.length === 0, jsErrors.join(' | '))
  } catch (e) {
    check('脚本执行完成', false, String(e).slice(0, 300))
    await page.screenshot({ path: path.join(OUT, 'L9_error.png'), fullPage: true }).catch(() => {})
  } finally {
    const pass = results.filter((r) => r.ok).length
    fs.writeFileSync(
      path.join(OUT, 'result.json'),
      JSON.stringify({ base: BASE, api: API, pass, total: results.length, results }, null, 2),
    )
    console.log(`\n${pass}/${results.length} PASS  →  ${OUT}/result.json`)
    await browser.close()
    process.exit(pass === results.length ? 0 : 1)
  }
})()
