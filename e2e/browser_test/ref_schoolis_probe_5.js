/**
 * 参考站点勘察 · 第 5 步：进入二级页面取形态（列表 / 表单 / 详情）
 * 用 evaluate 打标记再点击，绕开文本选择器在嵌套 div 里点不准的问题。
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

/** 在侧栏内按文本精确打标记，返回是否找到 */
async function markMenu(page, text) {
  return page.evaluate((t) => {
    document.querySelectorAll('[data-probe]').forEach((e) => e.removeAttribute('data-probe'))
    const sb = document.querySelector('[class*="menus"]') || document.body
    const cands = Array.from(sb.querySelectorAll('*')).filter((e) => {
      const own = Array.from(e.childNodes)
        .filter((n) => n.nodeType === 3)
        .map((n) => n.textContent.trim())
        .join('')
      return own === t
    })
    if (!cands.length) return false
    const el = cands[cands.length - 1]
    el.setAttribute('data-probe', '1')
    el.scrollIntoView({ block: 'center' })
    return true
  }, text)
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

  // 先展开一级菜单：点「教务管理」「教学管理」「系统管理」，让二级项挂载
  for (const top of ['教务管理', '教学管理', '系统管理']) {
    if (await markMenu(page, top)) {
      await page.waitForTimeout(900)
      await page.click('[data-probe="1"]').catch(() => {})
      await page.waitForTimeout(900)
    }
  }
  await page.screenshot({ path: path.join(OUT, 'M_expanded_menu.png') })

  // 展开后 dump 一次全量菜单（含二级）
  const full = await page.evaluate(() => {
    const sb = document.querySelector('[class*="menus"]')
    const out = []
    const walk = (el, d) => {
      for (const c of el.children) {
        const txt = (c.textContent || '').replace(/\s+/g, ' ').trim()
        const r = c.getBoundingClientRect()
        const cs = getComputedStyle(c)
        const own = Array.from(c.childNodes)
          .filter((n) => n.nodeType === 3)
          .map((n) => n.textContent.trim())
          .join('')
        if (own && r.height > 18 && r.height < 70) {
          out.push({
            d,
            text: own.slice(0, 18),
            h: Math.round(r.height),
            bg: cs.backgroundColor,
            color: cs.color,
            fs: cs.fontSize,
            fw: cs.fontWeight,
            radius: cs.borderRadius,
            padL: cs.paddingLeft,
          })
        }
        if (d < 4) walk(c, d + 1)
      }
    }
    walk(sb, 0)
    return out
  })
  fs.writeFileSync(path.join(OUT, 'menu_full.json'), JSON.stringify(full, null, 2))
  console.log('=== 菜单全量（前 45 项）===')
  full.slice(0, 45).forEach((i) =>
    console.log(
      `d${i.d} ${i.text.padEnd(12)} h=${i.h} bg=${i.bg.padEnd(22)} c=${i.color.padEnd(20)} r=${String(i.radius).padEnd(6)} pl=${i.padL}`,
    ),
  )

  // 进二级页
  const targets = ['学生', '考勤', '成绩', '员工账号', '班级']
  for (const t of targets) {
    if (!(await markMenu(page, t))) {
      console.log(`SKIP ${t}`)
      continue
    }
    try {
      await page.click('[data-probe="1"]', { timeout: 8000 })
      await page.waitForTimeout(3400)
      await page.screenshot({ path: path.join(OUT, `C_${t}.png`) })
      const info = await page.evaluate(() => {
        const tables = document.querySelectorAll('table').length
        const whiteCards = Array.from(document.querySelectorAll('div')).filter((e) => {
          const cs = getComputedStyle(e)
          const r = e.getBoundingClientRect()
          return cs.backgroundColor === 'rgb(255, 255, 255)' && r.width > 300 && r.height > 100
        }).length
        return {
          url: location.href,
          tables,
          whiteCards,
          text: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 100),
        }
      })
      console.log(`OK   ${t.padEnd(6)} tables=${info.tables} 白卡=${info.whiteCards}  ${info.url}`)
      console.log(`     「${info.text.slice(0, 80)}」`)
    } catch (e) {
      console.log(`ERR  ${t} — ${String(e).slice(0, 90)}`)
    }
  }

  await browser.close()
})()
