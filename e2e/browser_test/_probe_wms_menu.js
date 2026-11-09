// 仓储管理菜单（B-29）· 浏览器级验收
//
// 跑法（先 `DIST_DIR=frontend/dist_b29 PORT=5189 node scripts/serve_alpha.js`）：
//   BASE_URL=http://127.0.0.1:5189 node e2e/browser_test/_probe_wms_menu.js
//
// 断四件事：
//   A. admin 能看到「仓储管理」组，10 个子项文案与顺序对得上
//   B. 10 个子项逐个点进去：URL 正确、不落 /403、页面有实际内容（不是白屏）
//   C. test_inspector（M04 只读 26 条）同样看到 10 项 —— 有权的人不该被误伤
//   D. test_key_user（M04 = 0 条）**看不到**该组 —— 没权的人不该看见入口
//
// ★ C 与 D 是一对正负对照，缺一个都不成立：
//   只做 C 会漏掉"菜单根本没接权限、人人可见"；
//   只做 D 会漏掉"权限配太严、该看见的人看不见"。
//   这两个方向都不会报错，只会静默给出错误结果。
//
// ★ B 段判据为什么不用「0 控制台错误」：wms 几个页面在没有数据时会打 404 空态
//   （与 B-16 实验室详情页同一类噪音）。把 404 当红会让探针恒假红，
//   于是判据改成「落点不是 /403 + #app 有内容」—— 这才是"入口真的通了"。
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5189'
const TENANT = process.env.E2E_TENANT || 'MFG1'

const EXPECTED = [
  ['仓库结构', '/wms/warehouse-tree'],
  ['物料主数据', '/wms/materials'],
  ['入库单', '/wms/receipt-orders'],
  ['出库单', '/wms/issue-orders'],
  ['库存查询', '/wms/stock-query'],
  ['库存移动', '/wms/stock-move'],
  ['盘点管理', '/wms/inventory-counts'],
  ['批次管理', '/wms/batches'],
  ['库存预警', '/wms/alerts'],
  ['库存报表', '/wms/reports'],
]

const fails = []
let passed = 0
const ok = (n, d = '') => { passed += 1; console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`) }
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

async function login(page, user, pwd) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.clear())
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', user)
  await page.fill('input[type="password"]', pwd)
  const t = await page.$('input[name="tenant_id"], input[name="tenant"]')
  if (t) await t.fill(TENANT)
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 30000 })
}

/** 菜单里是否出现「仓储管理」组（父级 label 文本 + 可点） */
async function wmsGroup(page) {
  const groups = page.locator('.nav-submenu')
  const n = await groups.count()
  for (let i = 0; i < n; i += 1) {
    const g = groups.nth(i)
    const label = await g.locator('.nav-item.parent .nav-label').first().innerText().catch(() => '')
    if (label.trim() === '仓储管理') return g
  }
  return null
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })

  // ══ A. admin：组存在 + 10 项顺序正确 ══
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const pageErr = []
  page.on('pageerror', (e) => pageErr.push(String(e)))
  await login(page, process.env.E2E_ADMIN || 'mfg_admin', process.env.E2E_ADMIN_PWD || 'admin123')

  const g = await wmsGroup(page)
  chk('A1 admin 看到「仓储管理」组', !!g)

  if (!g) {
    await browser.close()
    console.log(`\n通 ${passed} / 断 ${fails.length}`)
    process.exit(0)
  }

  // 展开（子项默认 v-show=false）
  await g.locator('.nav-item.parent').first().click()
  await page.waitForTimeout(300)

  const subs = g.locator('.nav-item.sub')
  const gotLabels = []
  for (let i = 0; i < (await subs.count()); i += 1) {
    gotLabels.push((await subs.nth(i).locator('.nav-label').innerText()).trim())
  }
  chk('A2 子项数量 = 10', gotLabels.length === EXPECTED.length, `实际 ${gotLabels.length}`)
  chk('A3 子项文案与顺序正确',
    JSON.stringify(gotLabels) === JSON.stringify(EXPECTED.map((e) => e[0])),
    gotLabels.join(' / '))

  // ══ B. 逐个点进去 ══
  for (let i = 0; i < EXPECTED.length; i += 1) {
    const [label, path] = EXPECTED[i]
    // 手风琴：每次点击前确认组还开着（点别的组会关掉它，但这里只点本组子项）
    const link = g.locator('.nav-item.sub').nth(i)
    if (!(await link.isVisible())) {
      await g.locator('.nav-item.parent').first().click()
      await page.waitForTimeout(200)
    }
    await link.click()
    await page.waitForTimeout(600)

    const url = await page.evaluate(() => location.hash)
    const forbidden = url.includes('/403')
    const bodyLen = await page.evaluate(() => (document.querySelector('#app')?.innerText || '').length)
    chk(`B${i + 1} 「${label}」可进入`,
      !forbidden && url.includes(path) && bodyLen > 80,
      forbidden ? `落到 403（${url}）` : `${url} · 正文 ${bodyLen} 字`)
  }

  chk('B11 全程无 JS 异常', pageErr.length === 0, pageErr.slice(0, 2).join(' | '))
  await page.close()

  // ══ C. 有权限的非 admin 也该看见 ══
  const p2 = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  await login(p2, process.env.E2E_INSP || 'test_inspector', process.env.E2E_INSP_PWD || 'test123456')
  const g2 = await wmsGroup(p2)
  chk('C1 test_inspector（M04 只读 26 条）看到仓储组', !!g2)
  if (g2) {
    await g2.locator('.nav-item.parent').first().click()
    await p2.waitForTimeout(300)
    const cnt = await g2.locator('.nav-item.sub').count()
    chk('C2 同样 10 项可见', cnt === 10, `实际 ${cnt}`)
  }
  await p2.close()

  // ══ D. 无权限者不该看见（负向）══
  const p3 = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  await login(p3, process.env.E2E_NOPERM || 'test_key_user', process.env.E2E_NOPERM_PWD || 'test123456')
  const g3 = await wmsGroup(p3)
  chk('D1 test_key_user（M04 = 0 条）看不到仓储组', g3 === null,
    g3 ? '居然看见了 —— 菜单权限没生效' : '')
  await p3.close()

  await browser.close()
  console.log(`\n通 ${passed} / 断 ${fails.length}`)
  if (fails.length) { console.log('失败项：'); fails.forEach((f) => console.log('  - ' + f)) }
  process.exit(0)
})()
