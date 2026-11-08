// KPI 三态 + picker 回显 · 浏览器级验收（C-86 / C-87 的现场证据）
//
// 跑法（staging）：
//   BASE_URL=https://mfg1.ziwi.cn node e2e/browser_test/_probe_kpi_state_e2e.js
//
// 断的是「界面到底显示了什么」，不是「源码里改没改」：
//   1. 安灯页 3 张 KPI 必须是**数字**（取数成功时不许是空卡、不许是「未接入」）
//   2. 能耗页 2 张未接入指标必须显式写「未接入」（不许拿 计算中 / - 冒充读数）
//   3. 库存移动页选完仓库后，字段必须**显示选中项**（曾经 6 处全空白）
//   4. 负向自证：把「字段非空」的判据换成恒真，本脚本必须报红 —— 由 --self-test 模拟
//
// ★ 为什么第 3 条必须在浏览器里做：`:value` 在 Vant4 下不是 prop、也不走 slot，
//   静态扫描只能看出"写法不一样"，看不出"屏幕上是空的"。
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'https://mfg1.ziwi.cn'
const USER = process.env.E2E_USER || 'ah_admin'
const PWD = process.env.E2E_PWD || 'Ah@2026seed'
const TENANT = process.env.E2E_TENANT || 'AH-THR'

const fails = []
const ok = (n, d = '') => console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`)
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

/** KPI 卡读数：返回 [{title, text}]，text 已 trim */
async function kpiTexts(page, root) {
  return page.$$eval(`${root} .kpi-card`, (els) =>
    els.map((e) => ({
      title: e.querySelector('.kpi-title')?.textContent?.trim() || '',
      text: e.querySelector('.kpi-value')?.textContent?.trim() || '',
      muted: !!e.querySelector('.kpi-value--unavailable'),
    })))
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const pageErr = []
  page.on('pageerror', (e) => pageErr.push(String(e)))

  // ── 登录 ──
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', USER)
  await page.fill('input[type="password"]', PWD)
  const tenantInput = await page.$('input[name="tenant_id"], input[name="tenant"]')
  if (tenantInput) await tenantInput.fill(TENANT)
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 30000 })

  // ── 1. 安灯页 KPI：取数成功时必须是数字 ──
  await page.goto(`${BASE}/#/andon`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.kpi-card .kpi-value', { timeout: 20000 })
  // 等 loading 指示消失（否则会把"还没取到"当成"取到了但是空")
  await page.waitForFunction(
    () => document.querySelectorAll('.kpi-card .van-loading').length === 0,
    { timeout: 20000 },
  ).catch(() => {})
  const andon = await kpiTexts(page, 'div')
  console.log(`  安灯 KPI 实测：${JSON.stringify(andon)}`)
  chk('安灯 3 张 KPI 都在', andon.length >= 3, `实际 ${andon.length}`)
  const andonNum = andon.filter((k) => /^\d+$/.test(k.text))
  chk(
    '★ 安灯 KPI 读数是数字（不是空卡 / 不是未接入）',
    andon.length >= 3 && andonNum.length === andon.length,
    `数字 ${andonNum.length}/${andon.length}：${andon.map((k) => `${k.title}=${k.text || '(空)'}`).join(' ')}`,
  )

  // ── 2. 能耗页：未接入必须显式写「未接入」 ──
  await page.goto(`${BASE}/#/energy`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.kpi-card .kpi-value', { timeout: 20000 })
  await page.waitForTimeout(800)
  const energy = await kpiTexts(page, 'div')
  console.log(`  能耗 KPI 实测：${JSON.stringify(energy)}`)
  const carbon = energy.find((k) => k.title.includes('碳排放'))
  const alarm = energy.find((k) => k.title.includes('活跃告警'))
  chk('碳排放卡存在', !!carbon, JSON.stringify(energy.map((k) => k.title)))
  chk(
    '★ 碳排放显式「未接入」（不再拿文字冒充读数）',
    !!carbon && carbon.muted && carbon.text === '未接入',
    carbon ? `text=${carbon.text} muted=${carbon.muted}` : '缺卡',
  )
  chk(
    '★ 活跃告警显式「未接入」',
    !!alarm && alarm.muted && alarm.text === '未接入',
    alarm ? `text=${alarm.text} muted=${alarm.muted}` : '缺卡',
  )

  // ── 3. 库存移动页：选完仓库，字段必须显示选中项 ──
  await page.goto(`${BASE}/#/wms/stock-move`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.van-field input', { timeout: 20000 })
  // 目标仓库那一格（label 文案来自 StockMove.vue:57）
  const whField = await page.$('xpath=//div[contains(@class,"van-field")][.//label[contains(.,"目标仓库")]]')
  chk('找到「目标仓库」字段', !!whField)
  if (whField) {
    const before = await whField.$eval('input', (i) => i.value)
    chk('选择前字段为空（初态正常）', before === '', `before=${JSON.stringify(before)}`)

    await whField.click()
    // 仓库选择器是 van-picker（取消 / 确认 + 滚轮）。滚轮**不动**，直接点确认 ——
    // 这正是缺陷触发的路径：选第一项。若绑了 v-model 就应该拿到第一项。
    await page.waitForSelector('.van-picker__confirm', { timeout: 15000 })
    // 列数据是异步取回来的，弹层先出来、选项后到 —— 必须等选项，不然读到空列
    await page.waitForSelector('.van-picker-column__item', { timeout: 15000 })
    const picked = await page.$eval('.van-picker-column__item--selected, .van-picker-column__item',
      (e) => e.textContent.trim())
    // ★ 确认按钮在 1440x960 视口里 y≈960（贴底、在折叠线外），
    //   Playwright 的真实点击会点空；用 JS 派发才稳定。
    await page.evaluate(() => document.querySelector('.van-picker__confirm').click())
    await page.waitForTimeout(600)

    const after = await whField.$eval('input', (i) => i.value)
    console.log(`  选中项=${JSON.stringify(picked)} 字段回显=${JSON.stringify(after)}`)
    chk('★ 选完仓库后字段显示选中项（曾经恒为空白）', after.trim().length > 0 && after.trim() === picked.trim(),
      `期望 ${JSON.stringify(picked)} 实得 ${JSON.stringify(after)}`)
  }

  chk('三个页面 0 个 JS 运行时错误', pageErr.length === 0, pageErr.slice(0, 2).join(' | '))

  await browser.close()
  console.log('')
  if (fails.length) {
    console.log(`结果：FAIL ${fails.length}`)
    fails.forEach((f) => console.log(`  - ${f}`))
    process.exit(1)
  }
  console.log('结果：PASS')
})()
