// 临时诊断：KPI 卡片的 wide class 是否真的落到 DOM 且生效
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5185'
;(async () => {
  const b = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const p = await b.newPage({ viewport: { width: 1440, height: 960 } })
  await p.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await p.fill('input[name="username"], input[type="text"]', 'ah_admin')
  await p.fill('input[type="password"]', 'Ah@2026seed')
  const t = await p.$('input[name="tenant_id"], input[name="tenant"]')
  if (t) await t.fill('AH-THR')
  await p.click('button[type="submit"]')
  await p.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })
  await p.goto(`${BASE}/#/cockpit`, { waitUntil: 'domcontentloaded' })
  await p.waitForTimeout(3500)
  const r = await p.evaluate(() =>
    [...document.querySelectorAll('.cockpit__kpis')].map((g) => ({
      n: g.children.length,
      cols: getComputedStyle(g).gridTemplateColumns,
      kids: [...g.children].map((k) => ({
        cls: k.className,
        col: getComputedStyle(k).gridColumn,
        w: Math.round(k.getBoundingClientRect().width),
      })),
    })),
  )
  console.log(JSON.stringify(r, null, 1))
  await b.close()
})()
