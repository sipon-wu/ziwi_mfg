// 工作中心两条口径轴 · 浏览器级验收（B-23 的现场证据）
//
// 跑法（本地）：
//   BASE_URL=http://127.0.0.1:5188 E2E_USER=mfg_admin E2E_PWD=admin123 \
//   E2E_TENANT=MFG1 node e2e/browser_test/_probe_wctype_semantics.js
//
// 为什么静态闸绿了还要跑这个：
//   `test_wc_type_domain.py` 只能读源码文本 —— 它知道模板里写了「工艺性质」，
//   不知道这个字有没有真的渲染到屏幕上（Vant 的 cell label 会被折叠、被截断，
//   `th` 的 title 也不会出现在文本里）。而 B-23 的缺陷本身就是**文案级**的：
//   代码全绿、接口全 200，用户看到两个都叫「类型」的筛选器。
//
// 断五件事：
//   1. 工位列表表头是「工艺性质」，且 thead 里不再有「类型」
//   2. 表头带 title 说明「按工序现算」（悬浮能看到口径）
//   3. 工具条快速筛选的 placeholder 是「档案类别」
//   4. 新增表单里该字段叫「档案类别」，并且下方有兜底说明
//   5. 三个页面动作 0 JS 错误
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5188'
const USER = process.env.E2E_USER || 'mfg_admin'
const PWD = process.env.E2E_PWD || 'admin123'
const TENANT = process.env.E2E_TENANT || 'MFG1'

const fails = []
const ok = (n, d = '') => console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`)
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const pageErr = []
  page.on('pageerror', (e) => pageErr.push(String(e)))
  page.on('console', (m) => { if (m.type() === 'error') pageErr.push('console: ' + m.text()) })

  // ── 登录 ──
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', USER)
  await page.fill('input[type="password"]', PWD)
  const tenantInput = await page.$('input[name="tenant_id"], input[name="tenant"]')
  if (tenantInput) await tenantInput.fill(TENANT)
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 30000 })

  // ── 工位列表 ──
  await page.goto(`${BASE}/#/basics/work-centers`, { waitUntil: 'domcontentloaded' })
  // 等表体出来（列表是异步拉的；只等 th 会在空态骨架上也成立）
  await page.waitForFunction(
    () => document.querySelectorAll('table thead th').length > 0,
    { timeout: 20000 },
  )
  await page.waitForTimeout(1200)

  // ── 1. 表头文案 ──
  const ths = await page.$$eval('table thead th', (els) =>
    els.map((e) => ({ text: e.textContent.trim(), title: e.getAttribute('title') || '' })),
  )
  const texts = ths.map((t) => t.text)
  console.log(`  表头：${texts.join(' | ')}`)

  const natureTh = ths.find((t) => t.text === '工艺性质')
  chk('表头有「工艺性质」', !!natureTh, natureTh ? '' : `实际 ${JSON.stringify(texts)}`)
  chk('thead 里没有裸「类型」表头', !texts.includes('类型'), texts.includes('类型') ? '仍有一列表头叫「类型」' : '')
  chk(
    '表头 title 说明按工序现算',
    !!natureTh && natureTh.title.includes('工序'),
    natureTh ? `title="${natureTh.title}"` : '无该列',
  )

  // ── 2. 快速筛选 placeholder ──
  const phs = await page.$$eval('input', (els) => els.map((e) => e.placeholder).filter(Boolean))
  chk('快速筛选 placeholder 是「档案类别」', phs.includes('档案类别'), `实际 ${JSON.stringify(phs)}`)
  chk('不再出现旧 placeholder', !phs.some((p) => p.includes('工作中心类型')), JSON.stringify(phs))

  // ── 3. 「待核对」标记：档案值确有机会与派生值打架（只报不判，数据可能为 0） ──
  const conflict = await page.$$eval('.wc-conflict', (els) =>
    els.map((e) => e.getAttribute('title') || ''),
  )
  const rows = await page.$$eval('table tbody tr', (els) => els.length)
  console.log(`  当前页 ${rows} 行，待核对 ${conflict.length} 个`)
  if (conflict.length) console.log(`  例：${conflict[0]}`)
  chk('待核对提示同时说了档案值与派生值', conflict.length === 0 || conflict.some((t) => t.includes('档案填') && t.includes('工序')))

  // ── 4. 新增表单：字段名 + 兜底说明 ──
  // ★ 整段包 try：老版本构建里 Sheet 的根类名不同，`waitForSelector` 会直接抛
  //   未捕获异常把脚本打断 —— 那样只报一半结论、退出码还被管道吃掉（本项目栽过）。
  //   包起来之后，「打不开表单」本身就是一条 FAIL，后面的断言照常跑完。
  await page.click('text=新增工作中心')
  try {
    await page.waitForSelector('.ziwi-sheet', { timeout: 10000 })
    await page.waitForTimeout(600)
    const sheetText = await page.$eval('.ziwi-sheet', (e) => e.textContent || '')
    chk('表单字段叫「档案类别」', sheetText.includes('档案类别'), '')
    chk(
      '表单写明「只在尚未挂工序时作为兜底显示」',
      sheetText.includes('工艺性质') && sheetText.includes('兜底'),
      sheetText.includes('工艺性质') ? '' : '说明文案没渲染出来',
    )
    const hint = await page.$('.wc-type-hint')
    if (hint) {
      const box = await hint.boundingBox()
      chk('兜底说明可见且有高度', !!box && box.height > 0, box ? `${Math.round(box.width)}x${Math.round(box.height)}` : '无尺寸')
    } else {
      bad('兜底说明可见且有高度', '.wc-type-hint 没渲染出来')
    }
    await page.keyboard.press('Escape')
    await page.waitForTimeout(400)
  } catch (e) {
    bad('新增表单可打开', String(e.message || e).split('\n')[0])
    bad('表单字段叫「档案类别」', '表单没打开，无法判定')
    bad('表单写明「只在尚未挂工序时作为兜底显示」', '表单没打开，无法判定')
  }

  // ── 5. JS 错误 ──
  const realErr = pageErr.filter((e) => !/favicon|ResizeObserver/i.test(e))
  chk('全程 0 JS 错误', realErr.length === 0, realErr.slice(0, 3).join(' | '))

  await browser.close()
  console.log(`\n${fails.length === 0 ? '全部通过' : fails.length + ' 项失败'}`)
  if (fails.length) { fails.forEach((f) => console.log('  - ' + f)); process.exit(1) }
})()
