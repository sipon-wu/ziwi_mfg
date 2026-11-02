// B3 取证截图：选择器字段高度（三档）+ 看板新观感（三档）
// 只读，不改数据。
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUT = 'screenshots/b3_field_dashboard'

const TIERS = [
  { name: 'W', width: 1440, height: 900 },
  { name: 'T', width: 900, height: 700 },
  { name: 'H', width: 412, height: 915 },
]

;(async () => {
  const b = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })

  for (const tier of TIERS) {
    const p = await b.newPage({ viewport: { width: tier.width, height: tier.height } })
    await p.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
    await p.fill('input[name="username"], input[type="text"]', 'mfg_admin')
    await p.fill('input[type="password"]', 'admin123')
    await p.click('button[type="submit"]')
    await p.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })

    // 1) 工作中心列表：筛选栏 + 选择器
    await p.goto(`${BASE}/#/basics/work-centers`, { waitUntil: 'domcontentloaded' })
    await p.waitForTimeout(2000)
    await p.screenshot({ path: `${OUT}/${tier.name}_1_workcenter_list.png` })

    // 2) 展开选择器（W 档看锚定下拉，T/H 看底部浮层）
    const sel = await p.$('.ziwi-select .van-field')
    if (sel) {
      await sel.click()
      await p.waitForTimeout(600)
      await p.screenshot({ path: `${OUT}/${tier.name}_2_select_open.png` })
      await p.keyboard.press('Escape')
      await p.waitForTimeout(400)
    }

    // 3) 看板
    await p.goto(`${BASE}/#/dashboard`, { waitUntil: 'domcontentloaded' })
    await p.waitForTimeout(2200)
    await p.screenshot({ path: `${OUT}/${tier.name}_3_dashboard.png`, fullPage: true })

    await p.close()
    console.log(`shot ${tier.name} ok`)
  }

  await b.close()
})()
