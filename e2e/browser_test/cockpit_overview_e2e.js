// 驾驶舱 · 模块概览（丰富版）浏览器验收
// 跑法：
//   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
//   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
//   BASE_URL=http://127.0.0.1:5173 node e2e/browser_test/cockpit_overview_e2e.js
//
// 断的是"这页是否真的更丰富了"，不是"DOM 里有没有这个东西"：
// - KPI 卡 24 张、8 个模块、0 个「未接入」
// - 今日摘要条 5 项且数值**可读**（不是 '—'）
// - 占比条真的画出来了（宽度 > 0）
// - 卡片不再是等高拉伸（M11 比 M01 矮 —— 原来两列等高，短卡下半张全空）
// - 「进入」入口按权限出现，点击真的跳转
// - 触控目标 ≥ 48（外框实测，不看 CSS 变量文本）
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const USER = process.env.E2E_USER || 'ah_admin'
const PWD = process.env.E2E_PWD || 'Ah@2026seed'
const TENANT = process.env.E2E_TENANT || 'AH-THR'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/cockpit_overview'

const fs = require('fs')
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true })

const fails = []
const ok = (n, d = '') => console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`)
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

// M06 = 设备管理 TPM（权威编号见 backend/app/constants/modules.py::MODULE_NAMES）。
// 卡上原来写 M02，而 M02 是 BOM 管理 —— 与它自己的 perm 'M06:equipment:read' 自相矛盾。
const EXPECT_MODULES = ['M00', 'M01', 'M03', 'M04', 'M05', 'M06', 'M11', 'M12']

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const httpErr = []
  page.on('response', (r) => {
    if (r.url().includes('/api/v1') && r.status() >= 500) httpErr.push(`${r.status()} ${r.url()}`)
  })
  const pageErr = []
  page.on('pageerror', (e) => pageErr.push(String(e)))

  // ── 登录 ──
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', USER)
  await page.fill('input[type="password"]', PWD)
  const tenantInput = await page.$('input[name="tenant_id"], input[name="tenant"]')
  if (tenantInput) await tenantInput.fill(TENANT)
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 25000 })

  await page.goto(`${BASE}/#/cockpit`, { waitUntil: 'domcontentloaded' })
  // 等最后一格加载指示消失（每张 KPI 卡各自 loading）。
  // ★ 这里**不能**用裸 waitForFunction 直接抛：超时只会甩一句
  //   `TimeoutError`，看不出是哪几张卡、为什么卡住（实际踩过：模块卡 code
  //   改成 M06 而取数仍写 M02，setKpi 找不到卡 → 3 张卡永久 loading）。
  //   所以先软等，再把"还剩几张在转"当成一条断言报出来。
  let settled = true
  try {
    await page.waitForFunction(
      () => document.querySelectorAll('.ck .van-loading').length === 0,
      { timeout: 25000 },
    )
  } catch { settled = false }
  const stillLoading = await page.$$eval('.ck', (els) =>
    els.filter((e) => e.querySelector('.van-loading'))
      .map((e) => `${e.closest('.mod')?.querySelector('.mod__code')?.textContent?.trim() || '?'}/${e.querySelector('.ck__label')?.textContent?.trim() || '?'}`))
  chk('24 张 KPI 卡全部结束加载', settled && stillLoading.length === 0,
    settled ? '' : `25s 后仍有 ${stillLoading.length} 张在转：${stillLoading.join(' ')}`)
  await page.waitForTimeout(400)

  // ── 1. 模块与 KPI 数量 ──
  const mods = await page.$$eval('.mod', (els) =>
    els.map((e) => e.querySelector('.mod__code')?.textContent?.trim() || ''))
  chk('模块卡 8 张', mods.length === 8, `实际 ${mods.length}：${mods.join(',')}`)
  chk('模块编号齐全', EXPECT_MODULES.every((c) => mods.includes(c)), mods.join(','))

  const kpiCount = await page.$$eval('.mod .ck', (els) => els.length)
  chk('KPI 卡 24 张', kpiCount === 24, `实际 ${kpiCount}`)

  // ── 2. 有没有「未接入」 ──
  const unavailableLabels = await page.$$eval('.mod .ck', (els) =>
    els.filter((e) => e.querySelector('.ck__value--muted'))
      .map((e) => `${e.closest('.mod')?.querySelector('.mod__code')?.textContent?.trim()}/${e.querySelector('.ck__label')?.textContent?.trim()}`))
  chk('无「未接入」占位', unavailableLabels.length === 0, unavailableLabels.join(' '))

  // ── 3. 今日摘要：先证明值可读，再证明它是"块"而不是线 ──
  // ★ 这一组原先断的是"5 个 span 的文字内容"。但顶部摘要条曾经是**线分隔的
  //   文字带** —— 5 个 span 一个不少、值也都可读，断言全绿，而页面上半截仍是
  //   "一堆点线"。所以这里加两条只在"块"成立时才过的断言：5 块等宽、
  //   且每块有实心浅底（背景不是透明）。
  const today = await page.$$eval('.today__blocks .ck', (els) =>
    els.map((e) => {
      const r = e.getBoundingClientRect()
      const bg = getComputedStyle(e).backgroundColor
      return {
        k: e.querySelector('.ck__label')?.textContent?.trim() || '',
        v: e.querySelector('.ck__value')?.textContent?.trim() || '',
        w: Math.round(r.width),
        h: Math.round(r.height),
        bg,
      }
    }))
  chk('今日摘要 5 块', today.length === 5, today.map((t) => t.k).join('/'))
  const todayWidths = today.map((t) => t.w)
  chk('今日摘要 5 块等宽', today.length === 5
    && Math.max(...todayWidths) - Math.min(...todayWidths) <= 2,
    todayWidths.join('/'))
  // rgba(0, 0, 0, 0) / transparent = 还是白底文字，没做成块
  // ★ 必须同时要求 length > 0：空数组上跑 filter 得到 0 条，`=== 0` 恒真 ——
  //   整块都没渲染出来时这条断言反而是绿的（自己踩了一次：选择器改名后
  //   0 块被"全部都有底色"判为通过）。
  const transparent = today.filter((t) => /rgba?\(0,\s*0,\s*0,\s*0\)|transparent/.test(t.bg))
  chk('今日摘要每块有实心底色（不是裸文字）',
    today.length === 5 && transparent.length === 0,
    today.map((t) => `${t.k}:${t.bg}`).join(' ') || '一块都没渲染出来')

  // ★ 完工产出必须可读（它是这一条的主指标）；
  //   报废率在"完工 0 件"时**有意**给 '—'（0% 会被读成"质量很好"），不算缺席。
  const outItem = today.find((t) => t.k === '完工产出')
  const rateItem = today.find((t) => t.k === '报废率')
  chk('完工产出可读', !!outItem && /^\d/.test(outItem.v), outItem ? outItem.v : '整块缺失')
  const outNum = outItem ? parseInt(outItem.v, 10) : NaN
  chk('报废率仅在完工为 0 时可留空',
    !!rateItem && (Number.isFinite(outNum) && outNum > 0 ? /^[\d.]+/.test(rateItem.v) : rateItem.v === '—'),
    `完工=${outItem && outItem.v} 报废率=${rateItem && rateItem.v}`)

  // ── 4. 占比条真的画出来了 ──
  const bars = await page.$$eval('.ck__ratio', (els) =>
    els.map((e) => ({
      text: e.querySelector('.ck__ratio-text')?.textContent?.trim() || '',
      w: e.querySelector('.ck__fill')?.getBoundingClientRect().width || 0,
    })))
  chk('占比条 ≥ 2 条', bars.length >= 2, `${bars.length} 条：${bars.map((b) => b.text).join(' ')}`)
  // 0% 的条宽度就是 0，是合法的；只要求"有分母的条里至少一条宽度 > 0"
  chk('占比条有实际宽度', bars.length > 0 && bars.some((b) => b.w > 1),
    bars.map((b) => `${b.text}=${Math.round(b.w)}px`).join(' '))

  // ── 5. 布局：行内等高，但页面不留裸露空洞 ──
  // 卡片按 top 坐标分行，同一行内高度必须一致（否则短卡下方会露出页面底色）。
  const heights = await page.$$eval('.mod', (els) =>
    els.map((e) => {
      const r = e.getBoundingClientRect()
      return {
        code: e.querySelector('.mod__code')?.textContent?.trim(),
        top: Math.round(r.top),
        h: Math.round(r.height),
      }
    }))
  const rows = {}
  heights.forEach((x) => { (rows[x.top] = rows[x.top] || []).push(x) })
  const unequal = Object.values(rows).filter((r) => new Set(r.map((i) => i.h)).size > 1)
  chk('同一行卡片等高（不留页面底色空洞）', unequal.length === 0,
    equalCheckDetail(heights))

  function equalCheckDetail(hs) {
    const byRow = {}
    hs.forEach((x) => { (byRow[x.top] = byRow[x.top] || []).push(`${x.code}:${x.h}`) })
    return Object.values(byRow).map((r) => r.join('=')).join(' | ')
  }

  // ── 6. 进入入口 + 跳转 ──
  const enterCount = await page.$$eval('.mod__enter', (els) => els.length)
  chk('进入入口 7 个（外部产品线不给入口）', enterCount === 7, `实际 ${enterCount}`)

  // ── 6b. 同一模块内 KPI 卡等宽 ──
  // 进度条 / 长文案都会把 grid 列撑开（1fr 的最小值是 min-content），
  // 结果同一行里"工单"窄、"在制"宽，看着像没对齐。
  const widthSpread = await page.$$eval('.mod', (els) =>
    els.map((e) => {
      const ws = Array.from(e.querySelectorAll('.ck')).map((k) => Math.round(k.getBoundingClientRect().width))
      return {
        code: e.querySelector('.mod__code')?.textContent?.trim(),
        ws,
        spread: ws.length ? Math.max(...ws) - Math.min(...ws) : 0,
      }
    }))
  const ragged = widthSpread.filter((m) => m.spread > 2)
  chk('同一模块内 KPI 卡等宽', ragged.length === 0,
    ragged.length ? ragged.map((m) => `${m.code} 差${m.spread}px`).join(' ')
      : widthSpread.map((m) => `${m.code}:${m.ws.join('/')}`).join(' '))

  // 块状表达的前提是"块一样大"。只要有一张模块卡少了/多了项，
  // 它那几块就会比别人宽，整面矩阵立刻塌成"大小不一的色块"。
  const allW = widthSpread.flatMap((m) => m.ws)
  const gMin = Math.min(...allW)
  const gMax = Math.max(...allW)
  chk('全页 KPI 块宽度统一（矩阵不塌）', gMax - gMin <= 2, `${gMin}~${gMax}px`)

  // ── 7. 触控目标实测（外框，不看令牌文本） ──
  const geo = await page.evaluate(() => {
    const q = (s) => {
      const el = document.querySelector(s)
      return el ? Math.round(el.getBoundingClientRect().height) : null
    }
    return { more: q('.today__more'), head: q('.mod__head') }
  })
  chk('「生产报表」按钮 ≥ 48', typeof geo.more === 'number' && geo.more >= 48, `${geo.more}px`)
  chk('模块卡头 ≥ 48', typeof geo.head === 'number' && geo.head >= 48, `${geo.head}px`)

  // ── 8. 页脚口径说明 ──
  const foot = await page.$eval('.cockpit__foot', (e) => e.textContent || '')
  chk('页脚写明双口径不可相加', foot.includes('不认') || foot.includes('不可相加'),
    foot.slice(0, 40).replace(/\s+/g, ' '))

  await page.screenshot({ path: `${OUT}/C1_cockpit.png`, fullPage: true })

  // 滚到底再拍一张：主区是内部滚动容器，fullPage 抓不到下半页
  await page.evaluate(() => document.querySelector('.cockpit__foot')?.scrollIntoView({ block: 'end' }))
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}/C1b_cockpit_bottom.png` })

  // ── 9. 点「进入」跳仓储 ──
  const wmsMod = (await page.$$('.mod')).find
  const target = await page.evaluateHandle(() => {
    const m = Array.from(document.querySelectorAll('.mod'))
      .find((e) => e.querySelector('.mod__code')?.textContent?.trim() === 'M04')
    return m ? m.querySelector('.mod__head') : null
  })
  if (target) {
    await target.asElement().click()
    await page.waitForTimeout(700)
    const hash = await page.evaluate(() => location.hash)
    chk('点 M04「进入」跳到库存查询', hash.includes('/wms/stock-query'), hash)
    await page.screenshot({ path: `${OUT}/C2_jump_wms.png` })
  } else {
    bad('点 M04「进入」跳到库存查询', '找不到 M04 卡片')
  }

  // ── 10. 无 500 / JS 异常 ──
  chk('无 5xx', httpErr.length === 0, httpErr.slice(0, 3).join(' | '))
  chk('无 JS 异常', pageErr.length === 0, pageErr.slice(0, 2).join(' | '))

  await browser.close()

  console.log(`\n${fails.length === 0 ? 'PASS' : 'FAIL'} · 断点 ${fails.length}`)
  if (fails.length) fails.forEach((f) => console.log('  - ' + f))
  process.exit(fails.length ? 1 : 0)
})()
