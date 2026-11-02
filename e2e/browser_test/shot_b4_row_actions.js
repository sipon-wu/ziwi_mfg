// 行内操作结构性消掉的取证截图：点开一行看展开区的 .row-actions
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUT = 'screenshots/b4_row_actions'

const PAGES = [
  ['work-centers', '/basics/work-centers'],
  ['operations', '/basics/operations'],
  ['products', '/basics/products'],
  ['routes', '/basics/routes'],
]

;(async () => {
  const b = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })

  for (const [w, h, tier] of [
    [1440, 900, 'W'],
    [412, 915, 'H'],
  ]) {
    const p = await b.newPage({ viewport: { width: w, height: h } })
    await p.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
    await p.fill('input[name="username"], input[type="text"]', 'mfg_admin')
    await p.fill('input[type="password"]', 'admin123')
    await p.click('button[type="submit"]')
    await p.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })

    for (const [name, path] of PAGES) {
      await p.goto(`${BASE}/#${path}`, { waitUntil: 'domcontentloaded' })
      await p.waitForTimeout(1800)
      // 点第一行的编码单元格展开
      const cell = await p.$('tbody tr:not(.row-detail-row) td')
      if (!cell) {
        console.log(`${tier} ${name}: 无数据行，跳过`)
        continue
      }
      await cell.click()
      await p.waitForTimeout(600)
      await p.screenshot({ path: `${OUT}/${tier}_${name}.png` })
      const m = await p.evaluate(() => {
        const act = document.querySelector('.ziwi-row-actions')
        const btns = act ? Array.from(act.querySelectorAll('.van-button')) : []
        const heights = btns.map((b) => Math.round(b.getBoundingClientRect().height))
        const old = document.querySelectorAll('.op-btns').length
        return {
          hasActions: !!act,
          btnH: heights.length ? Math.min(...heights) : null,
          btnCount: btns.length,
          miniBtnsLeft: old,
        }
      })
      console.log(
        `${tier} ${name}: row-actions=${m.hasActions} 按钮数=${m.btnCount} ` +
          `最矮=${m.btnH} 残留op-btns=${m.miniBtnsLeft}`,
      )
    }
    await p.close()
  }
  await b.close()
})()
