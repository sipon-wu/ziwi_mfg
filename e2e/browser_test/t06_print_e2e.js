/**
 * T06 打印留痕 E2E（真实浏览器点击，不含任何 mock）。
 *
 * 覆盖四条只有真实浏览器才能证的路径：
 *  1. 工单详情页「打印流转卡」→ 进预览页（路由没被 `/print/:docType/:docId` 遮蔽）
 *  2. 预览页 iframe 拿到 `blob:` 的 PDF（服务端出的是真 PDF，不是 HTML 伪装）
 *  3. 预览页把留痕码显示出来（纸面与屏幕要对得上）
 *  4. 扫码回查页给出「有效」判读（二维码落点真的可用）
 *
 * 跑法（先起 backend:8000 + serve_alpha:5173）：
 *   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
 *   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
 *   node e2e/browser_test/t06_print_e2e.js
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_BASE || `${BASE}/api/v1`
const OUT = path.join(__dirname, 'screenshots', 'print')

const results = []
function record(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' :: ' + detail : ''}`)
}

async function apiLogin() {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'mfg_admin', password: 'admin123' }),
  })
  const j = await r.json()
  if (!j.access_token) throw new Error('登录失败：' + JSON.stringify(j).slice(0, 200))
  return j.access_token
}

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const token = await apiLogin()

  // 基准数据一律从接口现取，不写死 id（探针铁律）
  const woRes = await fetch(`${API}/work-orders?page=1&page_size=1`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then((r) => r.json())
  const wo = (woRes.data && woRes.data.items && woRes.data.items[0]) || null
  if (!wo) throw new Error('本地库没有工单，无法验证打印入口')
  console.log(`基准工单：${wo.wo_no} (id=${wo.id})`)

  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await ctx.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })

  // ── 登录 ──
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[type="text"], input[name="username"]', 'mfg_admin')
  await page.fill('input[type="password"]', 'admin123')
  await page.click('button[type="submit"]')
  // 登录落点按角色不同（admin 落 cockpit、班组落 dashboard），只要求离开 login 页
  await page.waitForURL((u) => !u.hash.startsWith('#/login'), { timeout: 20000 })
  await page.waitForLoadState('networkidle').catch(() => {})
  record('登录成功', true, page.url().split('#')[1])

  // ── 1. 详情页入口 ──
  await page.goto(`${BASE}/#/work-orders/${wo.id}`, { waitUntil: 'domcontentloaded' })
  const printBtn = page.locator('button:has-text("打印流转卡")')
  await printBtn.waitFor({ state: 'visible', timeout: 20000 })
  record('详情页出现「打印流转卡」按钮', true)
  await page.screenshot({ path: path.join(OUT, 'P1_detail_entry.png') })

  await printBtn.click()
  await page.waitForURL(/#\/print\/preview\/work_order\//, { timeout: 20000 })
  record('点击后进入打印预览页（路由未被遮蔽）', true, page.url().split('#')[1])

  // ── 2. iframe 里是真 PDF ──
  const frame = page.locator('iframe.print-page__frame')
  await frame.waitFor({ state: 'visible', timeout: 30000 })
  const src = await frame.getAttribute('src')
  record('预览 iframe 拿到 blob 源', !!src && src.startsWith('blob:'), src && src.slice(0, 12))

  // blob 内容必须是 %PDF-（服务端真出了 PDF，不是把 HTML 塞进去骗人）
  const isPdf = await page.evaluate(async (u) => {
    const buf = await (await fetch(u)).arrayBuffer()
    const head = new TextDecoder().decode(new Uint8Array(buf.slice(0, 5)))
    return { head, size: buf.byteLength }
  }, src)
  record('PDF 字节头为 %PDF-', isPdf.head === '%PDF-', `${isPdf.head} / ${isPdf.size}B`)

  // ── 3. 留痕码显示在页面上 ──
  const sub = await page.locator('.print-page__sub').innerText()
  const m = sub.match(/留痕码\s+([A-Z0-9]{4}-[A-Z0-9]{4})/)
  record('预览页显示留痕码', !!m, sub)
  await page.screenshot({ path: path.join(OUT, 'P2_preview.png'), fullPage: false })

  // ── 4. 扫码回查页 ──
  if (!m) {
    record('回查页判读', false, '拿不到留痕码，跳过')
  } else {
    const code = m[1]
    await page.goto(`${BASE}/#/print/verify/${code}`, { waitUntil: 'domcontentloaded' })
    const badge = page.locator('.verify-card__label')
    await badge.waitFor({ state: 'visible', timeout: 20000 })
    const verdict = (await badge.innerText()).trim()
    record('回查页给出明确判读', verdict === '有效', verdict)
    const body = await page.locator('.verify-page__body').innerText()
    record('回查页显示单号与版本', body.includes(wo.wo_no) && /第 \d+ 版/.test(body))
    await page.screenshot({ path: path.join(OUT, 'P3_verify.png'), fullPage: true })
  }

  // ── 5. 无 JS 报错 ──
  const real = errors.filter((e) => !/favicon|ResizeObserver/i.test(e))
  record('页面无 JS 报错', real.length === 0, real.slice(0, 3).join(' | '))

  await browser.close()

  const failed = results.filter((r) => !r.ok)
  fs.writeFileSync(
    path.join(OUT, 'result.json'),
    JSON.stringify({ base: BASE, wo: { id: wo.id, wo_no: wo.wo_no }, results }, null, 2),
  )
  console.log(`\n${results.length - failed.length}/${results.length} PASS`)
  process.exit(failed.length ? 1 : 0)
})().catch((e) => {
  console.error('E2E 异常：', e)
  process.exit(2)
})
