/**
 * 参考站点勘察 · 第 1 步：登录 + 落点识别
 * 目标 https://xiaobaowx.schoolis.cn/ —— 取 UI/交互参考，不改任何东西。
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.REF_BASE || 'https://xiaobaowx.schoolis.cn'
const USER = process.env.REF_USER || 'wuhao1'
const PASS = process.env.REF_PASS || 'gli123456'
const OUT = 'e2e/browser_test/screenshots/ref_schoolis'
fs.mkdirSync(OUT, { recursive: true })

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
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
  })
  const page = await ctx.newPage()
  const logs = []
  page.on('pageerror', (e) => logs.push('pageerror: ' + String(e).slice(0, 120)))
  page.on('console', (m) => {
    if (m.type() === 'error') logs.push('console: ' + m.text().slice(0, 120))
  })

  console.log('→ goto', BASE)
  const resp = await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 })
  console.log('  status', resp && resp.status(), ' url', page.url())
  await page.waitForTimeout(3500)
  await page.screenshot({ path: path.join(OUT, 'R0_landing.png') })
  console.log('  标题:', await page.title())

  // dump 表单结构：登录框有哪些字段
  const formInfo = await page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll('input')).map((i) => ({
      type: i.type,
      name: i.name,
      placeholder: i.placeholder,
      id: i.id,
      cls: (i.className || '').toString().slice(0, 60),
    }))
    const btns = Array.from(document.querySelectorAll('button')).map((b) => ({
      text: (b.textContent || '').trim().slice(0, 20),
      cls: (b.className || '').toString().slice(0, 60),
    }))
    return {
      url: location.href,
      inputs,
      btns: btns.slice(0, 10),
      hasIframe: !!document.querySelector('iframe'),
      iframes: Array.from(document.querySelectorAll('iframe')).map((f) => f.src),
      bodyText: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 300),
    }
  })
  console.log(JSON.stringify(formInfo, null, 2))

  // 尝试登录
  try {
    const textInputs = page.locator('input:not([type="password"]):not([type="hidden"])')
    const n = await textInputs.count()
    console.log('  可见文本输入框数:', n)
    if (n > 0) {
      await textInputs.first().fill(USER)
      const pw = page.locator('input[type="password"]')
      if (await pw.count()) await pw.first().fill(PASS)
      await page.screenshot({ path: path.join(OUT, 'R1_login_filled.png') })
      const submit = page.locator(
        'button[type="submit"], button:has-text("登录"), button:has-text("登 录"), .login-btn, input[type="submit"]',
      )
      if (await submit.count()) {
        await submit.first().click()
      } else {
        await page.keyboard.press('Enter')
      }
      await page.waitForTimeout(6000)
      await page.screenshot({ path: path.join(OUT, 'R2_after_login.png') })
      console.log('  登录后 url:', page.url())
      console.log('  登录后标题:', await page.title())
      const after = await page.evaluate(() => ({
        bodyText: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 400),
        localStorageKeys: Object.keys(localStorage || {}),
        sessionKeys: Object.keys(sessionStorage || {}),
      }))
      console.log(JSON.stringify(after, null, 2))
    }
  } catch (e) {
    console.log('登录尝试异常:', String(e).slice(0, 300))
  }

  console.log('\n--- 前端日志 ---')
  console.log(logs.slice(0, 12).join('\n') || '(无)')
  await browser.close()
})()
