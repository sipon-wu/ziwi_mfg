/**
 * 参考站点勘察 · 第 2 步：设计令牌 + 代表页截图
 * 只读浏览，不点任何新增/删除/提交类按钮。
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.REF_BASE || 'https://xiaobaowx.schoolis.cn'
const USER = process.env.REF_USER || 'wuhao1'
const PASS = process.env.REF_PASS || 'gli123456'
const OUT = 'e2e/browser_test/screenshots/ref_schoolis'
fs.mkdirSync(OUT, { recursive: true })

// 只读页面：列表 / 看板 / 设置类
const PAGES = [
  ['首页', '/newsis/index'],
  ['学生列表', '/newsis/student'],
  ['收款', '/newsis/finance/charge'],
  ['考勤', '/newsis/attendance'],
  ['员工账号', '/newsis/system/staff'],
]

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
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(3000)
  const ti = page.locator('input:not([type="password"]):not([type="hidden"])')
  if (await ti.count()) await ti.first().fill(USER)
  const pw = page.locator('input[type="password"]')
  if (await pw.count()) await pw.first().fill(PASS)
  await page.locator('button:has-text("立即登录"), .login-btn').first().click()
  await page.waitForFunction(() => !/login|passport/i.test(location.href), { timeout: 30000 })
  await page.waitForTimeout(4000)

  // ── 设计令牌：从真实渲染里读 ──
  const tokens = await page.evaluate(() => {
    const pick = (el, props) => {
      if (!el) return null
      const cs = getComputedStyle(el)
      const o = {}
      props.forEach((p) => (o[p] = cs[p]))
      return o
    }
    const px = (v) => v
    // 侧栏
    const sidebar = document.querySelector('aside, .ant-layout-sider, [class*="sider"], [class*="sidebar"]')
    // 顶栏
    const header = document.querySelector('.ant-layout-header, header, [class*="header"]')
    // 内容区
    const content = document.querySelector('.ant-layout-content, [class*="content"]')
    // 卡片
    const card = document.querySelector('.ant-card, [class*="card"]')
    // 一级菜单项
    const menuItem = document.querySelector('.ant-menu-item, [class*="menu-item"]')
    // 选中态
    const menuActive =
      document.querySelector('.ant-menu-item-selected, [class*="menu-item"][class*="active"]') || null
    // 主按钮
    const btnPrimary = document.querySelector('.ant-btn-primary')
    // 表格
    const table = document.querySelector('.ant-table, table')
    const th = document.querySelector('.ant-table-thead th, thead th')
    const td = document.querySelector('.ant-table-tbody td, tbody td')

    return {
      sidebar: {
        rect: sidebar
          ? (({ x, y, width, height }) => ({
              x: Math.round(x),
              y: Math.round(y),
              w: Math.round(width),
              h: Math.round(height),
            }))(sidebar.getBoundingClientRect())
          : null,
        style: pick(sidebar, ['backgroundColor', 'borderRight', 'width', 'position']),
      },
      header: {
        rect: header
          ? (({ x, y, width, height }) => ({
              x: Math.round(x),
              y: Math.round(y),
              w: Math.round(width),
              h: Math.round(height),
            }))(header.getBoundingClientRect())
          : null,
        style: pick(header, ['backgroundColor', 'height', 'borderBottom', 'boxShadow']),
      },
      content: pick(content, ['backgroundColor', 'padding']),
      bodyBg: getComputedStyle(document.body).backgroundColor,
      bodyFont: getComputedStyle(document.body).fontFamily,
      bodyFontSize: getComputedStyle(document.body).fontSize,
      bodyColor: getComputedStyle(document.body).color,
      card: pick(card, [
        'backgroundColor',
        'borderRadius',
        'border',
        'boxShadow',
        'padding',
      ]),
      menuItem: pick(menuItem, [
        'backgroundColor',
        'color',
        'fontSize',
        'height',
        'borderRadius',
        'paddingLeft',
      ]),
      menuActive: pick(menuActive, ['backgroundColor', 'color', 'fontWeight', 'borderRadius']),
      btnPrimary: pick(btnPrimary, [
        'backgroundColor',
        'color',
        'borderRadius',
        'height',
        'fontSize',
        'paddingLeft',
      ]),
      table: pick(table, ['borderRadius', 'border', 'fontSize']),
      th: pick(th, ['backgroundColor', 'color', 'fontSize', 'fontWeight', 'height', 'padding']),
      td: pick(td, ['color', 'fontSize', 'height', 'padding', 'borderBottom']),
      // AntD 主色变量
      antPrimary: getComputedStyle(document.documentElement).getPropertyValue('--ant-primary-color') || null,
      breakpoints: (() => {
        const out = []
        for (const s of document.styleSheets) {
          let rules
          try {
            rules = s.cssRules
          } catch {
            continue
          }
          if (!rules) continue
          for (const r of rules) {
            if (r.media && /max-width|min-width/.test(r.media.mediaText)) out.push(r.media.mediaText)
          }
        }
        return Array.from(new Set(out)).slice(0, 40)
      })(),
    }
  })
  fs.writeFileSync(path.join(OUT, 'tokens.json'), JSON.stringify(tokens, null, 2))
  console.log('=== 设计令牌 ===')
  console.log(JSON.stringify(tokens, null, 2))

  // ── 代表页截图 ──
  for (const [name, href] of PAGES) {
    try {
      await page.goto(BASE + href, { waitUntil: 'domcontentloaded', timeout: 45000 })
      await page.waitForTimeout(2600)
      await page.screenshot({ path: path.join(OUT, `P_${name}.png`) })
      const bt = await page.evaluate(() => (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 160))
      console.log(`OK  ${name.padEnd(8)} ${href}  「${bt.slice(0, 60)}」`)
    } catch (e) {
      console.log(`ERR ${name} ${href} — ${String(e).slice(0, 100)}`)
    }
  }

  await browser.close()
})()
