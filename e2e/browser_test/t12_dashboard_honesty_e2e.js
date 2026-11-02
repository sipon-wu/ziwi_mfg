// t12 · 看板「诚实性」回归
//
// 这一页改造前是脚手架占位，三处数据在骗人：
//   1. 卡名写「今日工单」，数据是全量 total
//   2. 第三张「产出总量」的 stats.output 从未赋值，恒 0 却当真实值渲染
//   3. 「较昨日持平」是三张卡写死的字符串，与数据无关
// 本脚本只锁这三条 + 三档不塌，不测样式细节（那是 shot 脚本的活）。
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'

const TIERS = [
  { name: 'W', width: 1440, height: 900, cols: 3 },
  { name: 'T', width: 900, height: 700, cols: 3 },
  { name: 'H', width: 412, height: 915, cols: 1 },
]

let pass = 0
let fail = 0
const rows = []
function check(tier, name, ok, evidence) {
  if (ok) pass++
  else fail++
  rows.push(`${ok ? 'PASS' : 'FAIL'}  [${tier}] ${name}  — ${evidence ?? ''}`)
}

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

    await p.goto(`${BASE}/#/dashboard`, { waitUntil: 'domcontentloaded' })
    await p.waitForTimeout(2200)

    const d = await p.evaluate(() => {
      const body = document.body.innerText
      const cards = Array.from(document.querySelectorAll('.kpi-card'))
      const info = cards.map((c) => {
        const r = c.getBoundingClientRect()
        return {
          title: (c.querySelector('.kpi-title')?.textContent || '').trim(),
          value: (c.querySelector('.kpi-value')?.textContent || '').trim(),
          unavailable: c.classList.contains('kpi-card--unavailable'),
          top: Math.round(r.top),
          left: Math.round(r.left),
          width: Math.round(r.width),
        }
      })
      return {
        hasFakeTrend: /较昨日/.test(body),
        hasTodayLabel: /今日工单|今日报工/.test(body),
        cards: info,
      }
    })

    check(tier.name, '没有写死的假趋势文案（较昨日…）', !d.hasFakeTrend, `hasFakeTrend=${d.hasFakeTrend}`)
    check(
      tier.name,
      '卡名不再谎称「今日」（数据是全量 total）',
      !d.hasTodayLabel,
      `hasTodayLabel=${d.hasTodayLabel}`,
    )
    check(tier.name, '看板有 3 张 KPI 卡', d.cards.length === 3, `${d.cards.length} 张`)

    const out = d.cards.find((c) => c.title.includes('产出'))
    check(
      tier.name,
      '「产出总量」标为未接入而不是假 0',
      !!out && out.unavailable && out.value === '未接入',
      out ? `value=${out.value} unavailable=${out.unavailable}` : '未找到该卡',
    )

    // 版面：同 top 的卡算一行，行数应等于预期
    const tops = [...new Set(d.cards.map((c) => c.top))]
    check(
      tier.name,
      `版面不塌（预期 ${tier.cols} 列 / ${Math.ceil(3 / tier.cols)} 行）`,
      tops.length === Math.ceil(3 / tier.cols),
      `实际 ${tops.length} 行，列宽 ${d.cards.map((c) => c.width).join('/')}`,
    )

    // 单列时卡片要够宽，不能被压成竖排
    if (tier.cols === 1) {
      const minW = Math.min(...d.cards.map((c) => c.width))
      check(tier.name, '单列卡片宽度 ≥ 300（文字不会被压成竖排）', minW >= 300, `${minW}px`)
    }

    check(tier.name, '无 JS 运行时错误', jsErrors.length === 0, jsErrors.join(' | '))
    await p.close()
  }

  await b.close()
  console.log(rows.join('\n'))
  console.log(`\n${pass}/${pass + fail} PASS`)
  process.exit(fail > 0 ? 1 : 0)
})()
