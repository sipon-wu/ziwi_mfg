// 量列表数据行高：行本身是"点行展开"的点击目标，不能低于 48
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'

const PAGES = [
  ['工作中心', '/basics/work-centers'],
  ['工序定义', '/basics/operations'],
  ['产品管理', '/basics/products'],
  ['工艺路线', '/basics/routes'],
  ['BOM', '/boms'],
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
      await p.waitForTimeout(1600)
      const d = await p.evaluate(() => {
        const tr = document.querySelector('tbody tr:not(.row-detail-row)')
        if (!tr) return null
        const r = tr.getBoundingClientRect()
        const td = tr.querySelector('td')
        const cs = td ? getComputedStyle(td) : null
        return {
          h: Math.round(r.height * 10) / 10,
          pad: cs ? cs.padding : '',
          lh: cs ? cs.lineHeight : '',
        }
      })
      console.log(
        `${tier} ${name.padEnd(6)} ${path.padEnd(22)} 行高=${d ? d.h : 'n/a'} pad=${d ? d.pad : ''} lh=${d ? d.lh : ''}`,
      )
    }
    await p.close()
  }
  await b.close()
})()
