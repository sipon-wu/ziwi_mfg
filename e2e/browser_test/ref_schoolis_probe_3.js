/**
 * 参考站点勘察 · 第 3 步：真实导航结构 + 关键元素样式 + 三档宽度自适应
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

  // ── 导航真实结构 ──
  const nav = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('a[href]')).map((a) => ({
      href: a.getAttribute('href'),
      text: (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 24),
      w: Math.round(a.getBoundingClientRect().width),
      h: Math.round(a.getBoundingClientRect().height),
    }))
    // 侧栏容器：找 fixed 定位且宽度 150-260 的元素
    const fixed = Array.from(document.querySelectorAll('*'))
      .filter((el) => {
        const cs = getComputedStyle(el)
        const r = el.getBoundingClientRect()
        return (
          (cs.position === 'fixed' || cs.position === 'absolute') &&
          r.width > 140 &&
          r.width < 300 &&
          r.height > 400
        )
      })
      .slice(0, 3)
      .map((el) => {
        const cs = getComputedStyle(el)
        const r = el.getBoundingClientRect()
        return {
          tag: el.tagName,
          cls: (el.className || '').toString().slice(0, 80),
          w: Math.round(r.width),
          bg: cs.backgroundColor,
          boxShadow: cs.boxShadow,
          borderRight: cs.borderRight,
        }
      })
    return { linkCount: links.length, links: links.slice(0, 60), fixed }
  })
  fs.writeFileSync(path.join(OUT, 'nav.json'), JSON.stringify(nav, null, 2))
  console.log('链接总数:', nav.linkCount)
  console.log('--- fixed 侧栏候选 ---')
  console.log(JSON.stringify(nav.fixed, null, 2))
  console.log('--- 前 40 个链接 ---')
  nav.links.slice(0, 40).forEach((l) => console.log(`  ${String(l.w).padStart(4)}×${l.h}  ${l.text.padEnd(12)} ${l.href}`))

  // ── 关键元素样式（用文本定位，不依赖类名）──
  const styles = await page.evaluate(() => {
    const byText = (txt) => {
      const els = Array.from(document.querySelectorAll('*')).filter(
        (e) => e.children.length === 0 && (e.textContent || '').trim() === txt,
      )
      return els[0] || null
    }
    const dump = (el, props) => {
      if (!el) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      const o = { rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] }
      props.forEach((p) => (o[p] = cs[p]))
      return o
    }
    const p = ['backgroundColor', 'color', 'fontSize', 'fontWeight', 'borderRadius', 'padding', 'height', 'boxShadow', 'border']
    return {
      首页: dump(byText('首页'), p),
      招生管理: dump(byText('招生管理'), p),
      一级菜单容器: (() => {
        const el = byText('招生管理')
        return el ? dump(el.parentElement, p) : null
      })(),
      顶栏系统切换: dump(byText('行政办公系统'), p),
      卡片候选: (() => {
        const els = Array.from(document.querySelectorAll('div')).filter((e) => {
          const cs = getComputedStyle(e)
          const r = e.getBoundingClientRect()
          return cs.backgroundColor === 'rgb(255, 255, 255)' && r.width > 200 && r.height > 80
        })
        return els.slice(0, 3).map((e) => ({
          cls: (e.className || '').toString().slice(0, 60),
          ...dump(e, p),
        }))
      })(),
    }
  })
  console.log('\n=== 关键元素样式 ===')
  console.log(JSON.stringify(styles, null, 2))
  fs.writeFileSync(path.join(OUT, 'styles.json'), JSON.stringify(styles, null, 2))

  await browser.close()
})()
