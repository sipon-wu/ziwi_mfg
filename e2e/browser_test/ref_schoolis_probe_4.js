/**
 * 参考站点勘察 · 第 4 步：点击式遍历导航 + 三档宽度自适应取证
 * 只点导航，不点任何新增/提交/删除。
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

/** 侧栏里所有"像菜单项"的元素的文本 + 坐标 + 是否一级 */
async function dumpMenu(page) {
  return page.evaluate(() => {
    const sb = document.querySelector('[class*="menus"]') || document.querySelector('[class*="sidebar"]')
    if (!sb) return { err: 'no sidebar', items: [] }
    const items = []
    const walk = (el, depth) => {
      for (const c of el.children) {
        const txt = (c.textContent || '').replace(/\s+/g, ' ').trim()
        const r = c.getBoundingClientRect()
        const cs = getComputedStyle(c)
        if (r.width > 100 && r.height > 18 && r.height < 70 && txt && txt.length < 20) {
          items.push({
            depth,
            text: txt,
            y: Math.round(r.y),
            h: Math.round(r.height),
            bg: cs.backgroundColor,
            color: cs.color,
            fs: cs.fontSize,
            fw: cs.fontWeight,
            radius: cs.borderRadius,
          })
        }
        if (depth < 3) walk(c, depth + 1)
      }
    }
    walk(sb, 0)
    const sbcs = getComputedStyle(sb)
    const r = sb.getBoundingClientRect()
    return {
      sidebar: {
        w: Math.round(r.width),
        bg: sbcs.backgroundColor,
        shadow: sbcs.boxShadow,
        radius: sbcs.borderRadius,
      },
      items: items.slice(0, 60),
    }
  })
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

  const menu = await dumpMenu(page)
  console.log('=== 侧栏 ===', JSON.stringify(menu.sidebar))
  console.log('=== 菜单项 ===')
  menu.items.forEach((i) =>
    console.log(
      `  d${i.depth} y=${String(i.y).padStart(4)} h=${i.h} bg=${i.bg.padEnd(22)} c=${i.color.padEnd(20)} r=${i.radius.padEnd(8)} ${i.text}`,
    ),
  )
  fs.writeFileSync(path.join(OUT, 'menu.json'), JSON.stringify(menu, null, 2))

  // ── 点几个有代表性的二级项，取证列表页 / 表单页形态 ──
  const targets = ['学生', '考勤', '收费', '订单', '员工账号', '课程表', '成绩']
  for (const t of targets) {
    try {
      const loc = page.locator(`text="${t}"`).first()
      if (!(await loc.count())) {
        console.log(`SKIP ${t}（找不到）`)
        continue
      }
      await loc.click({ timeout: 8000 })
      await page.waitForTimeout(3200)
      const url = page.url()
      await page.screenshot({ path: path.join(OUT, `C_${t}.png`) })
      const head = await page.evaluate(() =>
        (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 120),
      )
      console.log(`OK   ${t.padEnd(6)} → ${url}`)
      console.log(`     「${head.slice(0, 80)}」`)
    } catch (e) {
      console.log(`ERR  ${t} — ${String(e).slice(0, 90)}`)
    }
  }

  // ── 三档宽度自适应 ──
  console.log('\n=== 三档宽度自适应 ===')
  await page.goto(BASE + '/newsis/index', { waitUntil: 'domcontentloaded' }).catch(() => {})
  await page.waitForTimeout(2500)
  const widths = [
    [1440, 900, 'W1440'],
    [1024, 768, 'W1024'],
    [768, 1024, 'T768'],
    [414, 896, 'H414'],
  ]
  for (const [w, h, tag] of widths) {
    await page.setViewportSize({ width: w, height: h })
    await page.waitForTimeout(2200)
    await page.screenshot({ path: path.join(OUT, `A_${tag}.png`) })
    const m = await page.evaluate(() => {
      const sb = document.querySelector('[class*="menus"]')
      const r = sb ? sb.getBoundingClientRect() : null
      const sbcs = sb ? getComputedStyle(sb) : null
      // 顶栏
      const hd = document.querySelector('header, .ant-layout-header')
      const hr = hd ? hd.getBoundingClientRect() : null
      // 视口内横向溢出？
      const overflowX = document.documentElement.scrollWidth > window.innerWidth + 1
      return {
        sidebar: r
          ? {
              w: Math.round(r.width),
              visible: r.width > 0 && sbcs.display !== 'none' && sbcs.visibility !== 'hidden',
              display: sbcs.display,
              transform: sbcs.transform,
            }
          : null,
        headerH: hr ? Math.round(hr.height) : null,
        overflowX,
        docScrollW: document.documentElement.scrollWidth,
        docW: window.innerWidth,
        bodyText: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 70),
      }
    })
    console.log(`  ${tag} (${w}x${h})  ${JSON.stringify(m)}`)
  }

  await browser.close()
})()
