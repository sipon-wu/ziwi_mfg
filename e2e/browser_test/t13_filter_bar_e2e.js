// t13 · 筛选栏控件高度回归（B4「筛选栏统一 48」）
//
// 背景：改造前筛选栏里是「48 的选择器字段 + 32 的按钮」并排，
// 上边缘参差。`--van-button-small-height` 是 32px 的全局令牌，
// **不能抬** —— 表格行内的行内操作也吃 small 档，一抬行高从 48 涨到 72。
// 所以按容器收口：`.ziwi-filter-bar .van-button { height: 48 }`。
//
// 本脚本只断言"筛选栏内的按钮和字段都 ≥ 48"，不测间距与配色。
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'

// ★ 每页要求的最少筛选栏数量。写成数据而不是"看到 0 也放过"，
//   是因为第一版把路由写成 /production/schedule（真实是 /schedule），
//   页面 404、栏数为 0、断言空转，38 项全绿但零覆盖 —— 假绿比红更危险。
const PAGES = [
  ['工作中心', '/basics/work-centers', 1],
  ['工序定义', '/basics/operations', 1],
  ['产品管理', '/basics/products', 1],
  ['工艺路线', '/basics/routes', 1],
  ['工厂日历', '/basics/calendar', 3],
  ['工单管理', '/work-orders', 1],
  ['生产排产', '/schedule', 1],
  ['入库单', '/wms/receipt-orders', 1],
  ['出库单', '/wms/issue-orders', 1],
  ['库存查询', '/wms/stock-query', 1],
  ['检验单', '/quality', 1],
  ['安灯', '/andon', 1],
  ['试产', '/trials', 1],
]

const TIERS = [
  { name: 'W', width: 1440, height: 900 },
  { name: 'T', width: 900, height: 700 },
  { name: 'H', width: 412, height: 915 },
]

const MIN = 48
let pass = 0
let fail = 0
const rows = []
const failures = []

;(async () => {
  const b = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })

  for (const tier of TIERS) {
    const p = await b.newPage({ viewport: { width: tier.width, height: tier.height } })
    const jsErrors = []
    p.on('pageerror', (e) => jsErrors.push(e.message))

    await p.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
    await p.fill('input[name="username"], input[type="text"]', 'mfg_admin')
    await p.fill('input[type="password"]', 'admin123')
    await p.click('button[type="submit"]')
    await p.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })

    for (const [label, path, expectBars] of PAGES) {
      await p.goto(`${BASE}/#${path}`, { waitUntil: 'domcontentloaded' })
      await p.waitForTimeout(1500)

      const d = await p.evaluate((min) => {
        const bars = Array.from(document.querySelectorAll('.ziwi-filter-bar'))
        const bad = []
        let total = 0
        for (const bar of bars) {
          const ctrls = bar.querySelectorAll('.van-button, .van-field')
          for (const c of ctrls) {
            const r = c.getBoundingClientRect()
            if (r.height === 0 && r.width === 0) continue // 隐藏元素不计
            total++
            if (r.height < min - 0.5) {
              bad.push((c.textContent || c.className).trim().slice(0, 14) + `=${Math.round(r.height)}`)
            }
          }
        }
        return { barCount: bars.length, total, bad }
      }, MIN)

      // 先证明"确实扫到了东西"，再谈达标 —— 否则 404 页面也是 0 个不达标
      let ok = true
      let why = ''
      if (d.barCount < expectBars) {
        ok = false
        why = ` 期望≥${expectBars}栏，实际${d.barCount}栏（路由错或类名没挂上）`
      } else if (d.total === 0) {
        ok = false
        why = ' 栏内读不到任何控件'
      } else if (d.bad.length > 0) {
        ok = false
        why = ` 不达标: ${d.bad.join(', ')}`
      }

      if (ok) pass++
      else {
        fail++
        failures.push(`[${tier.name}] ${label} ${path}:${why}`)
      }
      rows.push(
        `${ok ? 'PASS' : 'FAIL'}  [${tier.name}] ${label.padEnd(6)} ${path.padEnd(22)} ` +
          `筛选栏=${d.barCount} 控件=${d.total}${why}`,
      )
    }

    const jsOk = jsErrors.length === 0
    if (jsOk) pass++
    else fail++
    rows.push(`${jsOk ? 'PASS' : 'FAIL'}  [${tier.name}] 无 JS 运行时错误  — ${jsErrors.join(' | ')}`)

    await p.close()
  }

  await b.close()
  console.log(rows.join('\n'))
  if (failures.length) console.log(`\n不达标明细:\n${failures.join('\n')}`)
  console.log(`\n${pass}/${pass + fail} PASS`)
  process.exit(fail > 0 ? 1 : 0)
})()
