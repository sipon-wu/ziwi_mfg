/**
 * 视觉对齐取证：把 mfg 实际渲染出来的值，与能碳 ECMS 源码里声明的值逐项比对。
 *
 * ## 为什么不靠人眼看截图
 * 「看起来像不像」无法回归。这里读 `getComputedStyle`，与 ECMS
 * （`ziwi_project_dna/frontend/src`）里写死的值做断言 —— ECMS 没有 CSS 变量，
 * 它的期望值就是它 scoped style 里的字面量，直接抄过来即可。
 *
 * 期望值的出处（全部摘自 ECMS 源码，非估计）：
 * - `views/EnergyOverview.vue` `.section{background:#fff;border:1px solid #e8eaed;
 *   border-radius:10px;padding:20px}` / `.section-header h3{font-size:15px;color:#333}`
 * - `views/DeviceProfile.vue` `.tag{border-radius:10px}` `.btn-primary{background:#0d7377}`
 * - `views/DeviceProfile.vue` `.modal{border-radius:12px}`
 * - `App.vue` `body{background:#f0f2f5;color:#333}`
 * - `layouts/MainLayout.vue` `.main-area{background:#f0f2f5}`
 *
 * 用法：
 *   BASE_URL=http://127.0.0.1:5173 \
 *   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
 *   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
 *   node e2e/browser_test/t08_visual_align_e2e.js
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_BASE || BASE.replace(/\/$/, '') + '/api/v1'
const USER = process.env.E2E_USER || 'mfg_admin'
const PASS = process.env.E2E_PASS || 'admin123'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/t08_visual_align'

fs.mkdirSync(OUT, { recursive: true })

const results = []
const notes = []
function check(name, ok, detail) {
  results.push({ name, ok, detail: detail === undefined ? '' : String(detail) })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail === undefined ? '' : '  — ' + detail}`)
}
/** 只记录、不计入闸门：已知结构差异，属于 B2/B3 范围，不是 B1 值对齐的失败。 */
function note(name, detail) {
  notes.push({ name, detail: String(detail) })
  console.log(`NOTE  ${name}  — ${detail}`)
}

/** ECMS 源码里的字面量（rgb 形式便于与 getComputedStyle 对比） */
const ECMS = {
  pageBg: 'rgb(240, 242, 245)',      // #f0f2f5
  textColor: 'rgb(51, 51, 51)',      // #333
  cardBorder: 'rgb(232, 234, 237)',  // #e8eaed
  cardRadius: '10px',
  tagRadius: '10px',
  dialogRadius: '12px',
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
    await page.waitForTimeout(1000)

    // ── 页面底色 ──
    const mainBg = await page.evaluate(() => {
      const el = document.querySelector('.main-area') || document.body
      return getComputedStyle(el).backgroundColor
    })
    check('页面底色 = ECMS #f0f2f5', mainBg === ECMS.pageBg, mainBg)

    // ── 三处结构性元素：卡片 / 标签 / 弹窗 ──
    const login = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: USER, password: PASS, tenant_code: 'mfg_demo' }),
    })
    const lb = await login.json()
    const tok = lb.access_token || (lb.data && lb.data.access_token)
    const listResp = await fetch(`${API}/work-orders?page=1&page_size=1`, {
      headers: { Authorization: 'Bearer ' + tok },
    })
    const lj = await listResp.json()
    const wo = ((lj.data || lj).items || [])[0]

    // 工单详情：既有带 title 的分组（状态日志），也有不带 title 的字段分组
    await page.goto(`${BASE}/#/work-orders/${wo.id}`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2200)

    const card = await page.evaluate(() => {
      const all = Array.from(
        document.querySelectorAll('.van-cell-group:not(.van-cell-group--inset)'),
      )
      // ★ 取样口径（踩过的坑）：Vant 4.9 的 CellGroup 在有 title 时返回
      //   `[renderTitle(), renderGroup()]` 的 Fragment —— 标题是分组的
      //   **兄弟节点，不是子节点**（见 node_modules/vant/es/cell-group/CellGroup.mjs）。
      //   所以 `g.querySelector('.van-cell-group__title')` 恒为 null。
      //
      // ★ 另一个坑：带标题的卡片被我们拆成"标题（上半截）+ 分组（下半截）"，
      //   下半截的上边框与上圆角按设计是 none/0。因此边框只能看**左边**、
      //   圆角只能看**左下**，否则会把一条正确的拼合判成失败。
      const box = all[0]
      if (!box) return null
      const cs = getComputedStyle(box)
      const prev = box.previousElementSibling
      const header =
        prev && prev.classList.contains('van-cell-group__title') ? prev : null
      const hs = header ? getComputedStyle(header) : null
      const t = header || document.querySelector('.van-cell-group__title')
      const ts = t ? getComputedStyle(t) : null
      return {
        groupCount: all.length,
        borderLeft:
          cs.borderLeftWidth + ' ' + cs.borderLeftStyle + ' ' + cs.borderLeftColor,
        borderColor: cs.borderLeftColor,
        radius: cs.borderBottomLeftRadius,
        bg: cs.backgroundColor,
        headerBg: hs ? hs.backgroundColor : null,
        headerRadiusTop: hs ? hs.borderTopLeftRadius : null,
        headerBorderTop: hs
          ? hs.borderTopWidth + ' ' + hs.borderTopStyle + ' ' + hs.borderTopColor
          : null,
        titleText: t ? (t.textContent || '').trim().slice(0, 20) : null,
        titleSize: ts ? ts.fontSize : null,
        titleColor: ts ? ts.color : null,
      }
    })
    check('存在普通 cell-group（非 inset）', !!card, card && card.borderColor)
    if (card) {
      check('卡片边框 = ECMS 1px #e8eaed', card.borderColor === ECMS.cardBorder, card.borderLeft)
      check('卡片圆角 = ECMS 10px', card.radius === ECMS.cardRadius, card.radius)
      check('卡片白底', card.bg === 'rgb(255, 255, 255)', card.bg)
      check(
        '卡片标题 15px（ECMS h3）',
        card.titleSize === '15px',
        `${card.titleSize}  「${card.titleText}」`,
      )
      check('卡片标题色 = #333', card.titleColor === ECMS.textColor, card.titleColor)
      // 标题是否已并进卡片：白底 + 上圆角 10 + 上边框（而不是浮在灰色页底上）
      const headerMerged =
        card.headerBg === 'rgb(255, 255, 255)' &&
        card.headerRadiusTop === ECMS.cardRadius &&
        card.headerBorderTop &&
        card.headerBorderTop.startsWith('1px solid')
      check('分组标题已并入卡片（白底+上圆角+上边框）', !!headerMerged, card.headerBorderTop)
    }

    // 文字主色
    const bodyColor = await page.evaluate(() => getComputedStyle(document.body).color)
    check('正文色 = ECMS #333', bodyColor === ECMS.textColor, bodyColor)

    await page.screenshot({ path: path.join(OUT, 'V1_cards.png'), fullPage: false })

    // 标签圆角：工作中心列表有大量 van-tag
    await page.goto(`${BASE}/#/basics/work-centers`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2200)
    const tagRadius = await page.evaluate(() => {
      const t = document.querySelector('.van-tag')
      return t ? getComputedStyle(t).borderTopLeftRadius : null
    })
    check('标签圆角 = ECMS 10px 药丸', tagRadius === ECMS.tagRadius, tagRadius)
    await page.screenshot({ path: path.join(OUT, 'V2_tags.png'), fullPage: false })

    // 弹窗圆角：临时挂一个 .van-dialog 取其实用值（Vant 全量样式已随 index.css 注入）
    const dlgRadius = await page.evaluate(() => {
      const el = document.createElement('div')
      el.className = 'van-dialog'
      el.style.display = 'block'
      document.body.appendChild(el)
      const r = getComputedStyle(el).borderTopLeftRadius
      el.remove()
      return r
    })
    check('弹窗圆角 = ECMS 12px', dlgRadius === ECMS.dialogRadius, dlgRadius)

    check('无 JS 运行时错误', jsErrors.length === 0, jsErrors.join(' | ').slice(0, 200))
  } catch (e) {
    check('脚本执行完成', false, String(e).slice(0, 300))
    await page.screenshot({ path: path.join(OUT, 'V9_error.png') }).catch(() => {})
  } finally {
    const pass = results.filter((r) => r.ok).length
    fs.writeFileSync(
      path.join(OUT, 'result.json'),
      JSON.stringify({ base: BASE, ecmsReference: ECMS, pass, total: results.length, results, notes }, null, 2),
    )
    console.log(`\n${pass}/${results.length} PASS  →  ${OUT}/result.json`)
    await browser.close()
    process.exit(pass === results.length ? 0 : 1)
  }
})()
