/**
 * B2 验收：枚举选择器（ZiwiSelect）三档形态必须不同。
 *
 * ## 断言口径来自 UE §3.2「枚举选择器」行（必须不同）
 * | 形态 | 容器 | 位置 | 遮罩 | 标题栏 |
 * |---|---|---|---|---|
 * | W | 自绘 fixed 下拉 | 锚定字段下方 | 无 | 无 |
 * | T/H | van-popup bottom | 视口底部 | 有 | 有 |
 *
 * ## 为什么每条断言都能证伪
 * - 「锚定」现在测真实几何：下拉顶边必须贴合字段底边（±8px）。改造前
 *   W 档也是底部浮层，此断言必红。
 * - 「无遮罩」查全局 `.van-overlay` 是否存在。若 W 档忘了关 overlay，必红。
 * - 「无标题栏」查 `.ziwi-select-panel__header`。若漏传 variant，必红。
 * - 「T/H 仍从底部升起」查距底 0px，防止把 W 档的改动误伤到另外两档。
 *
 * 用法：
 *   BASE_URL=http://127.0.0.1:5173 \
 *   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
 *   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
 *   node e2e/browser_test/t10_select_three_tier_e2e.js
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_BASE || BASE.replace(/\/$/, '') + '/api/v1'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/t10_select_tiers'
const USER = process.env.E2E_USER || 'mfg_admin'
const PASS = process.env.E2E_PASS || 'admin123'

fs.mkdirSync(OUT, { recursive: true })

const results = []
function check(tier, name, ok, detail) {
  results.push({ tier, name, ok, detail: detail === undefined ? '' : String(detail) })
  console.log(`${ok ? 'PASS' : 'FAIL'}  [${tier}] ${name}${detail === undefined ? '' : '  — ' + detail}`)
}

const TIERS = [
  { tier: 'W', w: 1440, h: 900 },
  { tier: 'T', w: 900, h: 700 },
  { tier: 'H', w: 412, h: 915 },
]

/** 每次读取当前浮层（两档容器不同，统一从 document 里找） */
const READ_FLOAT = () => {
  const dd = document.querySelector('.ziwi-select__dropdown')
  const popup = document.querySelector('.ziwi-select__popup')
  const box = dd || popup
  if (!box) return null
  const r = box.getBoundingClientRect()
  const panel = box.querySelector('.ziwi-select-panel')
  return {
    kind: dd ? 'dropdown' : 'popup',
    rect: {
      top: Math.round(r.top),
      left: Math.round(r.left),
      w: Math.round(r.width),
      h: Math.round(r.height),
      bottom: Math.round(r.bottom),
    },
    hasOverlay: !!document.querySelector('.van-overlay'),
    hasHeader: !!box.querySelector('.ziwi-select-panel__header'),
    hasSearch: !!box.querySelector('.ziwi-select-panel__search'),
    panelClass: panel ? panel.className : null,
    radius: getComputedStyle(box).borderTopLeftRadius,
    vw: window.innerWidth,
    vh: window.innerHeight,
    rowHeights: Array.from(box.querySelectorAll('.ziwi-select-list__row')).map((e) =>
      Math.round(e.getBoundingClientRect().height),
    ),
    optionCount: box.querySelectorAll('.ziwi-select-list__row').length,
    zIndex: getComputedStyle(box).zIndex,
    titleText: (box.querySelector('.ziwi-select-panel__title') || {}).textContent || '',
  }
}

/**
 * 浮层是否**可见**。
 *
 * ★ 必须用可见性、不能用存在性：W 档下拉是 `v-if`（关闭即移除），
 *   但 T/H 档的 `van-popup` 关闭后元素仍留在 DOM 里（Vant 用 `v-show` +
 *   transition），`querySelector` 依然能查到。按存在性判定会把"已经正确关闭"
 *   误报成失败 —— 这正是"探针假设错"而不是产品缺陷。
 */
const IS_OPEN = () => {
  const visible = (el) => {
    if (!el) return false
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden') return false
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0 && Number(cs.opacity) > 0.01
  }
  return {
    dropdown: visible(document.querySelector('.ziwi-select__dropdown')),
    popup: visible(document.querySelector('.ziwi-select__popup')),
  }
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })

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
    await page.waitForTimeout(2400)

    const actual = await page.evaluate(
      () => document.documentElement.getAttribute('data-form-factor') || '',
    )
    check(t.tier, `视口落入预期档（${t.w}x${t.h}）`, actual === t.tier, `实际 ${actual}`)

    const field = page.locator('.ziwi-select .van-field').first()
    const fb = await field.boundingBox()
    await field.click()

    const sel = t.tier === 'W' ? '.ziwi-select__dropdown' : '.ziwi-select__popup'
    await page.waitForSelector(sel, { timeout: 10000 })
    await page.waitForTimeout(700) // 等入场动效结束再量几何

    const f = await page.evaluate(READ_FLOAT)
    await page.screenshot({ path: path.join(OUT, `S_${t.tier}_open.png`) })

    if (t.tier === 'W') {
      check('W', '容器是自绘下拉（不是 van-popup）', f.kind === 'dropdown', f.kind)
      check(
        'W',
        '锚定在字段下方（±8px）',
        Math.abs(f.rect.top - (fb.y + fb.height)) <= 8,
        `下拉top=${f.rect.top} 字段bottom=${Math.round(fb.y + fb.height)}`,
      )
      check('W', '无遮罩（非模态）', f.hasOverlay === false, `overlay=${f.hasOverlay}`)
      check('W', '无标题栏', f.hasHeader === false, `header=${f.hasHeader}`)
      check('W', '宽度不铺满视口（< 70%）', f.rect.w / f.vw < 0.7, `${f.rect.w}/${f.vw}`)
      check('W', '宽度 ≥ 240（放得下副行）', f.rect.w >= 240, `${f.rect.w}px`)
      check('W', '层级高于 Vant 浮层（z ≥ 2000）', Number(f.zIndex) >= 2000, `z=${f.zIndex}`)
      check('W', '圆角 8px（比卡片小一档）', f.radius === '8px', f.radius)
      check('W', '右边界不越出视口', f.rect.left + f.rect.w <= f.vw + 1, `${f.rect.left + f.rect.w} vs ${f.vw}`)

      // 点外部关闭
      await page.mouse.click(8, Math.round(t.h / 2))
      await page.waitForTimeout(500)
      const afterOutside = await page.evaluate(IS_OPEN)
      check('W', '点外部关闭', afterOutside.dropdown === false, `仍打开=${afterOutside.dropdown}`)

      // 再点字段 toggle 打开 → 再点关闭
      await field.click()
      await page.waitForSelector('.ziwi-select__dropdown', { timeout: 6000 }).catch(() => {})
      await field.click()
      await page.waitForTimeout(450)
      const afterToggle = await page.evaluate(IS_OPEN)
      check('W', '再点字段可收起（toggle）', afterToggle.dropdown === false, `仍打开=${afterToggle.dropdown}`)
    } else {
      check(t.tier, '容器是底部分组浮层（van-popup）', f.kind === 'popup', f.kind)
      check(
        t.tier,
        '从视口底部升起（距底 0）',
        Math.abs(f.vh - f.rect.bottom) <= 1,
        `距底 ${f.vh - f.rect.bottom}px`,
      )
      check(t.tier, '有遮罩（模态）', f.hasOverlay === true, `overlay=${f.hasOverlay}`)
      check(t.tier, '有标题栏', f.hasHeader === true, `header=${f.hasHeader}「${f.titleText}」`)
      check(
        t.tier,
        '宽度铺满视口',
        Math.abs(f.rect.w - f.vw) <= 1,
        `${f.rect.w}/${f.vw}`,
      )
    }

    // 三档共同项：行高热区不得低于触屏底线
    const minRow = f.rowHeights.length ? Math.min(...f.rowHeights) : null
    check(t.tier, '选项行高 ≥ 48（触屏底线）', minRow !== null && minRow >= 48, `${minRow}px`)
    check(t.tier, '选项列表非空', f.optionCount > 0, `${f.optionCount} 项`)
    check(t.tier, '无 JS 运行时错误', errs.length === 0, errs.join(' | ').slice(0, 160))

    // 键盘 Esc 关闭（三档都要能用）
    await page.keyboard.press('Escape')
    await page.waitForTimeout(500)
    const afterEsc = await page.evaluate(IS_OPEN)
    const closedByEsc = !afterEsc.dropdown && !afterEsc.popup
    check(t.tier, 'Esc 可关闭', closedByEsc, `dropdown=${afterEsc.dropdown} popup=${afterEsc.popup}`)

    await ctx.close()
  }

  const pass = results.filter((r) => r.ok).length
  fs.writeFileSync(
    path.join(OUT, 'result.json'),
    JSON.stringify({ base: BASE, pass, total: results.length, results }, null, 2),
  )
  console.log(`\n${pass}/${results.length} PASS  →  ${OUT}/result.json`)
  await browser.close()
  process.exit(pass === results.length ? 0 : 1)
})()
