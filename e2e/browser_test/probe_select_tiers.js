/**
 * 三档形态下「枚举选择器」的呈现取证（只测量，不改代码）。
 *
 * 回答的问题：同一个 SelectField（工作中心类型），在 W / T / H 三档下
 * 弹出的是不是同一种浮层？
 *
 * 只采集四个客观量：
 * - `html[data-form-factor]`：判定出的形态，用来确认视口真的落进了预期档
 * - 浮层几何：宽度占视口比例、距底边距离、圆角 → 判断是不是"底部浮层"
 * - 触发字段与浮层的位置关系 → 判断是不是"下拉浮层锚在字段下方"
 * - 每一档的截图
 *
 * 用法：
 *   BASE_URL=http://127.0.0.1:5173 \
 *   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
 *   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
 *   node e2e/browser_test/probe_select_tiers.js
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_BASE || BASE.replace(/\/$/, '') + '/api/v1'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/probe_select_tiers'
const USER = process.env.E2E_USER || 'mfg_admin'
const PASS = process.env.E2E_PASS || 'admin123'

fs.mkdirSync(OUT, { recursive: true })

// 三档各取一个能真正落进该档的视口
const TIERS = [
  { tier: 'W', w: 1440, h: 900, note: '办公 PC / 21.5" 工位一体机（横屏，宽 ≥1024）' },
  { tier: 'T', w: 900, h: 700, note: '10" 平板横置（600 ≤ 宽 < 1024）' },
  { tier: 'H', w: 412, h: 915, note: 'PDA / 手持机（宽 < 600）' },
]

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })

  // token 用接口拿，不依赖前端存储键名
  const login = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS, tenant_code: 'mfg_demo' }),
  })
  const lb = await login.json()
  const tok = lb.access_token || (lb.data && lb.data.access_token)
  if (!tok) throw new Error('登录失败：' + JSON.stringify(lb).slice(0, 200))

  const rows = []

  for (const t of TIERS) {
    const ctx = await browser.newContext({
      viewport: { width: t.w, height: t.h },
      deviceScaleFactor: 1,
    })
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

    const actualTier = await page.evaluate(
      () => document.documentElement.getAttribute('data-form-factor') || '',
    )

    // 触发字段：搜索栏里那个「工作中心类型」
    const field = page.locator('.ziwi-select .van-field').first()
    const fieldBox = await field.boundingBox()
    await field.click()
    await page.waitForSelector('.ziwi-select__popup .ziwi-select__panel', { timeout: 10000 })
    await page.waitForTimeout(600) // 等入场动效结束再量

    const geo = await page.evaluate(() => {
      const panel = document.querySelector('.ziwi-select__popup .ziwi-select__panel')
      const popup = document.querySelector('.ziwi-select__popup')
      if (!panel || !popup) return null
      const r = panel.getBoundingClientRect()
      const pr = popup.getBoundingClientRect()
      const cs = getComputedStyle(popup)
      return {
        panelW: Math.round(r.width),
        panelH: Math.round(r.height),
        popupW: Math.round(pr.width),
        popupTop: Math.round(pr.top),
        gapToViewportBottom: Math.round(window.innerHeight - pr.bottom),
        gapToViewportLeft: Math.round(pr.left),
        radius: cs.borderTopLeftRadius + ' / ' + cs.borderBottomLeftRadius,
        vw: window.innerWidth,
        vh: window.innerHeight,
        hasSearchBox: !!document.querySelector('.ziwi-select__search'),
        optionCount: document.querySelectorAll('.ziwi-select__popup .van-cell, .ziwi-select__popup li').length,
        titleText: (document.querySelector('.ziwi-select__title') || {}).textContent || '',
      }
    })

    // 锚定判定：浮层顶边是否紧贴触发字段底边（下拉浮层）还是从屏幕底部升起（底部浮层）
    const anchoredBelowField =
      geo && fieldBox ? Math.abs(geo.popupTop - (fieldBox.y + fieldBox.height)) < 24 : false

    await page.screenshot({ path: path.join(OUT, `P_${t.tier}_selector_open.png`) })

    rows.push({
      tier: t.tier,
      viewport: `${t.w}x${t.h}`,
      actualTier,
      note: t.note,
      ...geo,
      widthRatio: geo ? +(geo.popupW / geo.vw).toFixed(3) : null,
      anchoredBelowField,
      jsErrors: errs.length,
    })
    await ctx.close()
  }

  fs.writeFileSync(path.join(OUT, 'result.json'), JSON.stringify(rows, null, 2))
  console.log(JSON.stringify(rows, null, 2))

  // 结论行
  const same = rows.every(
    (r) =>
      r.widthRatio === rows[0].widthRatio &&
      r.gapToViewportBottom === rows[0].gapToViewportBottom &&
      r.hasSearchBox === rows[0].hasSearchBox,
  )
  console.log(
    `\n三档呈现是否一致：${same ? '一致（完全相同）' : '不一致'}  ` +
      `| 宽度占比 ${rows.map((r) => r.widthRatio).join(' / ')}  ` +
      `| 距底 ${rows.map((r) => r.gapToViewportBottom).join(' / ')}px`,
  )

  await browser.close()
})()
