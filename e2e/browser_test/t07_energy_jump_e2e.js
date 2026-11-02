/**
 * 能碳入口取证：mfg 左侧只剩一个跳转，不再有本系统功能导航。
 *
 * 断言四件事：
 * 1. 侧栏出现「能碳管理」外链，href 指向 ECMS，target=_blank + rel 含 noopener
 * 2. 该条**没有**可展开的子菜单（曾经的 4 个子页必须消失）
 * 3. 点它不会改变 mfg 的路由（是跳出去，不是站内切换）
 * 4. `/energy` 下的占位页不再出现在菜单里
 *
 * 用法：
 *   BASE_URL=http://127.0.0.1:5173 \
 *   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
 *   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
 *   node e2e/browser_test/t07_energy_jump_e2e.js
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_BASE || BASE.replace(/\/$/, '') + '/api/v1'
const USER = process.env.E2E_USER || 'mfg_admin'
const PASS = process.env.E2E_PASS || 'admin123'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/t07_energy_jump'

fs.mkdirSync(OUT, { recursive: true })

const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail: detail === undefined ? '' : String(detail) })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail === undefined ? '' : '  — ' + detail}`)
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const jsErrors = []
  page.on('pageerror', (e) => jsErrors.push(String(e)))

  try {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="username"], input[type="text"]', USER)
    await page.fill('input[type="password"]', PASS)
    await page.click('button[type="submit"]')
    await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })
    await page.waitForTimeout(1200)

    // 1) 外链存在且属性正确
    const link = page.locator('nav.sidebar-nav a:has-text("能碳管理")')
    check('侧栏有「能碳管理」外链', (await link.count()) > 0, await link.count())

    const href = await link.first().getAttribute('href')
    const target = await link.first().getAttribute('target')
    const rel = await link.first().getAttribute('rel')
    check('href 指向外部系统', !!href && /^https?:\/\//.test(href), href)
    check('新标签打开', target === '_blank', target)
    check('带 noopener（防被跳转页反向控制）', (rel || '').includes('noopener'), rel)

    // 2) 不再有子菜单
    const subItems = page.locator('nav.sidebar-nav .nav-item.sub:visible')
    const subTexts = await subItems.allTextContents()
    const formerChildren = ['用能概况', '能耗分析', '碳管理']
    const leaked = formerChildren.filter((t) => subTexts.some((s) => s.trim() === t))
    check('原有 4 个子页已从菜单消失', leaked.length === 0, leaked.join(',') || '无')

    // 3) 父级不再是可展开项（没有 nav-arrow）
    const arrowInItem = await link.first().locator('.nav-arrow').count()
    check('该条不再渲染展开箭头', arrowInItem === 0, arrowInItem)

    await page.screenshot({ path: path.join(OUT, 'E1_sidebar.png'), fullPage: false })

    // 4) 点击不改变 mfg 路由（会在新标签打开，当前页保持不动）
    const before = page.url()
    await link.first().click()
    await page.waitForTimeout(1200)
    const after = page.url()
    check('点击后 mfg 当前页不变（不是站内跳转）', before === after, after)

    // 5) 站内路由表里不应再有 /energy 的菜单入口
    const navTexts = (await page.locator('nav.sidebar-nav').allTextContents()).join(' ')
    check('菜单里不再出现「用能概况」', !navTexts.includes('用能概况'))

    check('无 JS 运行时错误', jsErrors.length === 0, jsErrors.join(' | '))
  } catch (e) {
    check('脚本执行完成', false, String(e).slice(0, 300))
    await page.screenshot({ path: path.join(OUT, 'E9_error.png') }).catch(() => {})
  } finally {
    const pass = results.filter((r) => r.ok).length
    fs.writeFileSync(
      path.join(OUT, 'result.json'),
      JSON.stringify({ base: BASE, pass, total: results.length, results }, null, 2),
    )
    console.log(`\n${pass}/${results.length} PASS  →  ${OUT}/result.json`)
    await browser.close()
    process.exit(pass === results.length ? 0 : 1)
  }
})()
