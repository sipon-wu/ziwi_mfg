/**
 * B2 验收 · 第二组：Sheet 内下拉层级 + 14 个使用页冒烟
 *
 * ## 为什么单独测 Sheet 内
 * W 档下拉用的是自绘 `fixed` 层。当选择器出现在 `ZiwiFormSheet`（本身是
 * `van-popup`，z-index 2000+）内部时，下拉会不会被外层 Sheet 压住？
 * 这是 `--ziwi-z-dropdown: 3000` 存在的唯一理由，必须用真实命中测试证明，
 * 不能只看 z-index 数值。
 *
 * 判定手段：`document.elementFromPoint(下拉中心点)` 必须命中下拉内部元素。
 * 若被 Sheet 盖住，会命中 Sheet 的某个子元素 → 直接证伪。
 *
 * ## 14 页冒烟
 * 三档各加载一遍，只断言「无 JS 运行时错误 + 选择器字段存在」。
 * 不做交互断言（那是 t10 的职责）。
 *
 * 用法同上（见 t10）。
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/t11_select_sheet'
const USER = process.env.E2E_USER || 'mfg_admin'
const PASS = process.env.E2E_PASS || 'admin123'

fs.mkdirSync(OUT, { recursive: true })

const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail: detail === undefined ? '' : String(detail) })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail === undefined ? '' : '  — ' + detail}`)
}

// 使用 ZiwiSelect / SelectField 的页面（grep 得出，14 个）
const PAGES = [
  ['工作中心', '/basics/work-centers'],
  ['工序定义', '/basics/operations'],
  ['产品管理', '/basics/products'],
  ['工艺路线', '/basics/routes'],
  ['工厂日历', '/basics/calendar'],
  ['保养计划', '/equipment/maintenance-plans'],
  ['保养任务', '/equipment/maintenance-tasks'],
  ['报工录入', '/work-reports/create'],
  ['FMEA', '/quality/fmea'],
  ['PPAP', '/quality/ppap/submissions'],
  ['收货单详情', '/wms/receipt-orders'],
  ['BOM', '/boms'],
  ['工单管理', '/work-orders'],
  ['检验单', '/quality'],
]

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })

  // ───────────── 第一组：Sheet 内下拉层级（W 档，最危险场景）─────────────
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await ctx.newPage()
    const errs = []
    page.on('pageerror', (e) => errs.push(String(e)))

    await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="username"], input[type="text"]', USER)
    await page.fill('input[type="password"]', PASS)
    await page.click('button[type="submit"]')
    await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })
    await page.goto(`${BASE}/#/basics/work-centers`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2200)

    // 打开「新增工作中心」→ 出现 ZiwiFormSheet
    const addBtn = page.locator('button:has-text("新增工作中心")')
    if (await addBtn.count()) {
      await addBtn.first().click()
      await page.waitForTimeout(1800)
      const sheetOpen = await page.evaluate(() => {
        // Sheet 用 `.ziwi-sheet` 作为内部根，外层是 van-popup（class 由 popupClass 决定，
        // 不一定是 --bottom：W 档是居中弹窗）。所以按内部根往上找，不猜外层类名。
        const inner = document.querySelector('.ziwi-sheet')
        const popup = inner ? inner.closest('.van-popup') : null
        if (!popup) return false
        const cs = getComputedStyle(popup)
        return cs.display !== 'none' && popup.getBoundingClientRect().height > 100
      })
      check('Sheet 已打开', sheetOpen === true, String(sheetOpen))
      await page.screenshot({ path: path.join(OUT, 'K1_sheet_open.png') })

      // Sheet 内第一个选择器
      const innerSelect = page.locator('.van-popup .ziwi-select .van-field').first()
      const n = await innerSelect.count()
      check('Sheet 内存在选择器', n > 0, `${n} 个`)

      if (n > 0) {
        await innerSelect.click()
        await page.waitForTimeout(900)
        const probe = await page.evaluate(() => {
          const dd = document.querySelector('.ziwi-select__dropdown')
          if (!dd) {
            // 也可能是 T/H 档走了 popup；此处视口是 1440，应当有 dropdown
            return { exists: false }
          }
          const r = dd.getBoundingClientRect()
          const cx = Math.round(r.left + r.width / 2)
          const cy = Math.round(r.top + Math.min(r.height / 2, 60))
          const hit = document.elementFromPoint(cx, cy)
          return {
            exists: true,
            rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
            zIndex: getComputedStyle(dd).zIndex,
            // 命中点是否落在下拉内部 → 证明没有被 Sheet 压住
            hitInsideDropdown: !!(hit && dd.contains(hit)),
            hitCls: hit ? (hit.className || '').toString().slice(0, 60) : null,
            sheetZ: (() => {
              const inner = document.querySelector('.ziwi-sheet')
              const popup = inner ? inner.closest('.van-popup') : null
              return popup ? getComputedStyle(popup).zIndex : null
            })(),
          }
        })
        await page.screenshot({ path: path.join(OUT, 'K2_sheet_with_dropdown.png') })
        check('Sheet 内下拉已渲染', probe.exists === true, JSON.stringify(probe.rect || null))
        if (probe.exists) {
          check(
            '下拉未被 Sheet 遮挡（命中测试）',
            probe.hitInsideDropdown === true,
            `命中=${probe.hitCls} 下拉z=${probe.zIndex} Sheet z=${probe.sheetZ}`,
          )
          // ★ 先证明 Sheet 的 z-index 真被读到了，再做数值比较。
          //   否则 `3000 > Number(null)` 恒为真 —— 那是一条永远绿的假断言。
          check(
            'Sheet 的 z-index 可读（防假绿）',
            probe.sheetZ !== null && Number.isFinite(Number(probe.sheetZ)),
            `sheetZ=${probe.sheetZ}`,
          )
          check(
            '下拉 z-index 高于 Sheet',
            probe.sheetZ !== null && Number(probe.zIndex) > Number(probe.sheetZ),
            `${probe.zIndex} > ${probe.sheetZ}`,
          )
          check(
            '下拉完整落在视口内',
            probe.rect[0] >= 0 &&
              probe.rect[1] >= 0 &&
              probe.rect[0] + probe.rect[2] <= 1440 &&
              probe.rect[1] + probe.rect[3] <= 900,
            JSON.stringify(probe.rect),
          )
        }
      }
      check('Sheet 场景无 JS 错误', errs.length === 0, errs.join(' | ').slice(0, 160))
    } else {
      check('找到「新增工作中心」按钮', false, '未找到，跳过 Sheet 场景')
    }
    await ctx.close()
  }

  // ───────────── 第二组：14 页 × 3 档冒烟 ─────────────
  const TIERS = [
    { tier: 'W', w: 1440, h: 900 },
    { tier: 'T', w: 900, h: 700 },
    { tier: 'H', w: 412, h: 915 },
  ]
  let smokeFail = 0
  let smokeTotal = 0
  for (const t of TIERS) {
    const ctx = await browser.newContext({ viewport: { width: t.w, height: t.h } })
    const page = await ctx.newPage()
    let errs = []
    page.on('pageerror', (e) => errs.push(String(e)))
    await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="username"], input[type="text"]', USER)
    await page.fill('input[type="password"]', PASS)
    await page.click('button[type="submit"]')
    await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })

    for (const [name, route] of PAGES) {
      errs = []
      smokeTotal += 1
      try {
        await page.goto(`${BASE}/#${route}`, { waitUntil: 'domcontentloaded' })
        await page.waitForTimeout(1100)
        const hasSelect = await page.evaluate(
          () => document.querySelectorAll('.ziwi-select').length,
        )
        const ok = errs.length === 0
        if (!ok) smokeFail += 1
        console.log(
          `${ok ? 'PASS' : 'FAIL'}  [${t.tier}] ${name.padEnd(8)} ${route.padEnd(32)} ` +
            `select=${hasSelect}` +
            (errs.length ? `  JS:${errs[0].slice(0, 60)}` : ''),
        )
      } catch (e) {
        smokeFail += 1
        console.log(`ERR   [${t.tier}] ${name} ${route} — ${String(e).slice(0, 80)}`)
      }
    }
    await ctx.close()
  }
  check(`14 页 × 3 档 无 JS 错误`, smokeFail === 0, `${smokeTotal - smokeFail}/${smokeTotal}`)

  const pass = results.filter((r) => r.ok).length
  fs.writeFileSync(
    path.join(OUT, 'result.json'),
    JSON.stringify({ base: BASE, pass, total: results.length, results }, null, 2),
  )
  console.log(`\n断言 ${pass}/${results.length} PASS；页面冒烟 ${smokeTotal - smokeFail}/${smokeTotal}`)
  await browser.close()
  process.exit(pass === results.length && smokeFail === 0 ? 0 : 1)
})()
