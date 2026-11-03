/**
 * 探针：工具栏统一改造（第二轮 7 页 + 第一轮 8 页）—— 视觉与结构双验。
 *
 * 对每页只回答三件事：
 * 1. 页面里是否只剩一个 `.ziwi-list-toolbar`（而不是残留 van-search）；
 * 2. 输入框与「搜索」按钮的水平间距是否 ≤ 24px（证明按钮没被推开）；
 * 3. 工具栏内可点元素高度是否统一在 --ziwi-touch-min（48）。
 *
 * 另外抓 console error 与 4xx/5xx 请求，避免"看着对了其实接口 404"。
 */
const fs = require('fs')
const path = require('path')
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.join(__dirname, 'screenshots', 'toolbar_round2')

const PAGES = [
  ['工序定义', '/#/basics/operations'],
  ['工作中心', '/#/basics/work-centers'],
  ['产品', '/#/basics/products'],
  ['工艺路线', '/#/basics/routes'],
  ['工单管理', '/#/work-orders'],
  ['安灯', '/#/andon'],
  ['检验管理', '/#/quality'],
  ['不合格品评审', '/#/quality/ncr'],
  ['设备台账', '/#/equipment'],
  ['BOM管理', '/#/boms'],
  ['批次管理', '/#/wms/batches'],
  ['盘点管理', '/#/wms/inventory-counts'],
  ['出库单管理', '/#/wms/issue-orders'],
  ['物料主数据', '/#/wms/materials'],
  ['入库单管理', '/#/wms/receipt-orders'],
]

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  const errors = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`[console] ${m.text().slice(0, 200)}`)
  })
  // 记录每页在观察窗口内打到 /api/v1 的请求数：>4 次说明列表在空转重试
  let apiHits = 0
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/')) apiHits++
  })
  page.on('response', (r) => {
    if (r.status() >= 400) errors.push(`[http ${r.status()}] ${r.url().slice(0, 160)}`)
  })

  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', 'mfg_admin')
  await page.fill('input[type="password"]', 'admin123')
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })

  const rows = []
  for (const [name, hash] of PAGES) {
    errors.length = 0
    apiHits = 0
    await page.goto(`${BASE}${hash}`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2200)

    const m = await page.evaluate(() => {
      const tb = document.querySelector('.ziwi-list-toolbar')
      if (!tb) return { has: false }
      const field = tb.querySelector('.ziwi-list-toolbar__input .van-field')
      const btns = [...tb.querySelectorAll('.van-button')]
      // 搜索按钮不能用文案匹配：loading 时文案被 spinner 顶掉，textContent 是空的
      const search = tb.querySelector('.ziwi-list-toolbar__input .van-button')
      const fb = field ? field.getBoundingClientRect() : null
      const sb = search ? search.getBoundingClientRect() : null
      return {
        has: true,
        gap: fb && sb ? Math.round((sb.left - fb.right) * 10) / 10 : null,
        heights: btns.map((b) => Math.round(b.getBoundingClientRect().height)),
        actionTexts: [...tb.querySelectorAll('.ziwi-list-toolbar__actions .van-button')].map((b) =>
          b.textContent.trim(),
        ),
        legacySearch: document.querySelectorAll('.van-search').length,
        searchLoading: !!search && search.classList.contains('van-button--loading'),
        // 查询组与操作组是否同一行（纵向重叠）
        sameRow:
          btns.length > 1
            ? Math.abs(btns[0].getBoundingClientRect().top - btns[btns.length - 1].getBoundingClientRect().top) < 4
            : null,
      }
    })

    const shot = path.join(OUT, `${String(rows.length + 1).padStart(2, '0')}_${name}.png`)
    await page.screenshot({ path: shot, clip: { x: 0, y: 0, width: 1440, height: 320 } })

    const hs = m.heights || []
    const uniform = hs.length > 0 && hs.every((h) => h === hs[0])
    const pass =
      m.has === true &&
      m.gap !== null &&
      m.gap <= 24 &&
      m.legacySearch === 0 &&
      uniform &&
      hs[0] >= 44

    rows.push({ name, pass, ...m, apiHits, uniform, errs: errors.slice(0, 3) })
    console.log(
      `${pass ? '[PASS]' : '[FAIL]'} ${name.padEnd(12)} 工具栏=${m.has ? 'Y' : 'N'} ` +
        `间距=${m.gap} 高=${JSON.stringify(hs)} 残留van-search=${m.legacySearch} ` +
        `同排=${m.sameRow} 搜索转圈=${m.searchLoading} 请求=${apiHits} 操作=${JSON.stringify(m.actionTexts || [])}` +
        (errors.length ? ` 错误=${errors.slice(0, 2).join(' | ')}` : ''),
    )
  }

  const bad = rows.filter((r) => !r.pass)
  console.log(`\n合计 ${rows.length} 页，PASS ${rows.length - bad.length} / FAIL ${bad.length}`)
  fs.writeFileSync(
    path.join(OUT, 'result.json'),
    JSON.stringify({ base: BASE, rows }, null, 2),
    'utf-8',
  )
  await browser.close()
  process.exit(bad.length ? 1 : 0)
})()
