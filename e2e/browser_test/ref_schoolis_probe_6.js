/**
 * 参考站点勘察 · 第 6 步：有数据的表格 / 筛选下拉 / 弹层形态
 * 严格只读：只切 tab、开下拉、开设置面板，不点任何「新建/保存/提交/删除」。
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.REF_BASE || 'https://xiaobaowx.schoolis.cn'
const OUT = 'e2e/browser_test/screenshots/ref_schoolis'
fs.mkdirSync(OUT, { recursive: true })

async function login(page) {
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2800)
  const ti = page.locator('input:not([type="password"]):not([type="hidden"])')
  if (await ti.count()) await ti.first().fill(process.env.REF_USER || 'wuhao1')
  const pw = page.locator('input[type="password"]')
  if (await pw.count()) await pw.first().fill(process.env.REF_PASS || 'gli123456')
  await page.locator('button:has-text("立即登录"), .login-btn').first().click()
  await page.waitForFunction(() => !/login|passport/i.test(location.href), { timeout: 30000 })
  await page.waitForTimeout(3500)
  // 关掉可能出现的引导浮层
  for (const t of ['跳过', '我知道了', '知道了']) {
    const b = page.locator(`button:has-text("${t}")`)
    if (await b.count()) await b.first().click().catch(() => {})
  }
  await page.waitForTimeout(800)
}

/** 按坐标点击文本元素（绕开 locator 可见性判定） */
async function clickText(page, text, nth = 0) {
  const pos = await page.evaluate(
    ({ t, n }) => {
      const cands = Array.from(document.querySelectorAll('*')).filter((e) => {
        const own = Array.from(e.childNodes)
          .filter((x) => x.nodeType === 3)
          .map((x) => x.textContent.trim())
          .join('')
        if (own !== t) return false
        const r = e.getBoundingClientRect()
        return r.width > 8 && r.height > 8
      })
      if (!cands.length) return null
      const el = cands[Math.min(n, cands.length - 1)]
      const r = el.getBoundingClientRect()
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }
    },
    { t: text, n: nth },
  )
  if (!pos) return false
  await page.mouse.click(pos.x, pos.y)
  return true
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
    locale: 'zh-CN',
  })
  const page = await ctx.newPage()
  await login(page)

  // 1) 学生页 → 切「全部学生」看有数据表格
  await page.goto(BASE + '/newsis/student', { waitUntil: 'domcontentloaded' }).catch(() => {})
  await page.waitForTimeout(3000)
  await clickText(page, '全部学生')
  await page.waitForTimeout(3200)
  await page.screenshot({ path: path.join(OUT, 'S1_all_students.png') })

  const tableInfo = await page.evaluate(() => {
    const th = document.querySelector('thead th')
    const td = document.querySelector('tbody td')
    const tr = document.querySelector('tbody tr')
    const cs = (e) => (e ? getComputedStyle(e) : null)
    const r = (e) => (e ? (({ x, y, width, height }) => ({ x: Math.round(x), y: Math.round(y), w: Math.round(width), h: Math.round(height) }))(e.getBoundingClientRect()) : null)
    return {
      hasTable: !!document.querySelector('table'),
      rowCount: document.querySelectorAll('tbody tr').length,
      th: cs(th)
        ? {
            bg: cs(th).backgroundColor,
            color: cs(th).color,
            fs: cs(th).fontSize,
            fw: cs(th).fontWeight,
            h: r(th).h,
            pad: cs(th).padding,
            border: cs(th).borderBottom,
          }
        : null,
      td: cs(td)
        ? {
            color: cs(td).color,
            fs: cs(td).fontSize,
            h: r(td) ? r(td).h : null,
            pad: cs(td).padding,
            border: cs(td).borderBottom,
          }
        : null,
      rowH: r(tr) ? r(tr).h : null,
      text: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 140),
    }
  })
  console.log('=== 学生表格 ===')
  console.log(JSON.stringify(tableInfo, null, 2))
  fs.writeFileSync(path.join(OUT, 'table.json'), JSON.stringify(tableInfo, null, 2))

  // 2) 打开一个筛选下拉，取浮层形态
  await clickText(page, '全部学期')
  await page.waitForTimeout(1400)
  await page.screenshot({ path: path.join(OUT, 'S2_filter_dropdown.png') })
  const dd = await page.evaluate(() => {
    const pops = Array.from(document.querySelectorAll('div')).filter((e) => {
      const cs = getComputedStyle(e)
      const r = e.getBoundingClientRect()
      return (
        cs.position === 'absolute' &&
        cs.backgroundColor === 'rgb(255, 255, 255)' &&
        r.width > 80 &&
        r.height > 40 &&
        r.height < 600
      )
    })
    return pops.slice(0, 2).map((e) => {
      const cs = getComputedStyle(e)
      const r = e.getBoundingClientRect()
      return {
        cls: (e.className || '').toString().slice(0, 50),
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
        radius: cs.borderRadius,
        shadow: cs.boxShadow,
        border: cs.border,
        text: (e.innerText || '').replace(/\s+/g, ' ').slice(0, 60),
      }
    })
  })
  console.log('=== 筛选下拉浮层 ===')
  console.log(JSON.stringify(dd, null, 2))
  await page.keyboard.press('Escape')

  // 3) 首页图标宫格区域放大
  await page.goto(BASE + '/newsis/index', { waitUntil: 'domcontentloaded' }).catch(() => {})
  await page.waitForTimeout(3000)
  await page.screenshot({ path: path.join(OUT, 'S3_home_full.png') })
  await page.screenshot({
    path: path.join(OUT, 'S4_home_icons_zoom.png'),
    clip: { x: 150, y: 60, width: 620, height: 230 },
  })
  await page.screenshot({
    path: path.join(OUT, 'S5_home_numbers_zoom.png'),
    clip: { x: 150, y: 250, width: 620, height: 190 },
  })

  // 4) 侧栏放大，看层级与角标
  await page.screenshot({
    path: path.join(OUT, 'S6_sidebar_zoom.png'),
    clip: { x: 0, y: 40, width: 180, height: 640 },
  })

  await browser.close()
  console.log('\n截图已存', OUT)
})()
