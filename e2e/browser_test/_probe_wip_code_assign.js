// 报工录入页「自动赋码」· 浏览器级验收（B-30 的现场证据）
//
// 跑法（本地，先 `DIST_DIR=frontend/dist_b30 PORT=5188 node scripts/serve_alpha.js`）：
//   BASE_URL=http://127.0.0.1:5188 E2E_USER=mfg_admin E2E_PWD=admin123 \
//   E2E_TENANT=MFG1 node e2e/browser_test/_probe_wip_code_assign.js
//
// 为什么 HTTP 探针绿了还要跑这个：
//   `wip_code_assign_e2e.py` 证明的是**接口返回了码**，它一行前端代码都没碰。
//   而这里最容易坏的地方恰恰是「接口 200、界面看不见」：码生成了但没人告诉现场，
//   等于没生成 —— 码是要贴到实物上的，看不见就得去批次台账里翻。
//
// 断四件事：
//   1. 报工页能正常渲染（工单选择 / 工序编码 / 合格数量都在）
//   2. 填「工序编码 = CW010」+ 合格数量 2 提交后，弹出「已生成 2 个部件码」
//   3. 弹窗里那两串码是 TD-YYYYMMDD-流水号（与后端码形对得上，不是随便一段文本）
//   4. 全过程 0 JS 错误
//
// ★ 赋码节点是**字典配的**（`trace_code_node`）。本探针依赖租户已灌：
//   `./.venv/Scripts/python.exe migrations/20261109_trace_code_rule_seed.py --tenant MFG1`
//   没灌就没码，弹窗不会出现 —— 那时会红在 #2，报错信息里会提示去灌字典。
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5188'
const USER = process.env.E2E_USER || 'mfg_admin'
const PWD = process.env.E2E_PWD || 'admin123'
const TENANT = process.env.E2E_TENANT || 'MFG1'

const fails = []
let passed = 0
const ok = (n, d = '') => { passed += 1; console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`) }
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

/**
 * 按标签文本定位 vant field 里的输入框。
 *
 * ★ 用 XPath 的 `normalize-space()` 而不是 CSS 的 `:text-is()`：模板换行会在
 *   标签里留下多余空白（innerText.trim() 看着是「工序编码」，DOM 里却是
 *   "\n          工序编码\n        "），`:text-is` 要求逐字符相等 → 永远不命中，
 *   表现为 `page.fill` 一直等到超时（第一次就是这么栽的）。
 */
const fieldInput = (label) =>
  `xpath=//*[contains(@class,"van-field__label") and normalize-space(.)="${label}"]` +
  `/ancestor::*[contains(@class,"van-field")][1]//input`

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

  // ── 用页面自己的 token 造一张「已下达」的工单（赋码要有工单才有物料可挂）──
  const wo = await page.evaluate(async (tag) => {
    const token = localStorage.getItem('access_token')
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'X-Tenant-Id': localStorage.getItem('tenant_id') || '',
    }
    const api = '/api/v1'
    const mat = await fetch(`${api}/wms/materials`, {
      method: 'POST', headers,
      body: JSON.stringify({
        code: `E2E-WCUI-${tag}`, name: `UI赋码${tag}`, unit: 'PCS',
        material_type: 'semi', is_batch_managed: true,
      }),
    }).then((r) => r.json())
    const mid = mat?.data?.id
    if (!mid) return { error: '建物料失败 ' + JSON.stringify(mat).slice(0, 200) }
    const made = await fetch(`${api}/work-orders`, {
      method: 'POST', headers,
      body: JSON.stringify({
        wo_no: `E2E-WCUI-WO-${tag}`, product_code: `E2E-WCUI-${tag}`,
        product_name: `UI赋码${tag}`, planned_qty: 4, wo_type: 'production',
        remark: 'E2E 自动赋码 UI 探针',
      }),
    }).then((r) => r.json())
    const wid = made?.data?.id
    if (!wid) return { error: '建工单失败 ' + JSON.stringify(made).slice(0, 200) }
    const rel = await fetch(`${api}/work-orders/${wid}/release`, {
      method: 'POST', headers,
    }).then((r) => r.json())
    if (rel?.code !== 0 && !rel?.data) {
      return { error: '下达工单失败 ' + JSON.stringify(rel).slice(0, 200) }
    }
    return { wid, woNo: `E2E-WCUI-WO-${tag}` }
  }, Date.now().toString().slice(-10))

  chk('P0 前置就绪（物料 + 已下达工单）', !wo.error, wo.error || `wo=${wo.woNo}`)
  if (wo.error) {
    await browser.close()
    console.log(`\n通 ${passed} / 断 ${fails.length}`)
    process.exit(0)
  }

  // ── C1 页面渲染 ──
  await page.goto(`${BASE}/#/work-reports/create`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.wrf-form', { timeout: 20000 })
  chk('C1 报工页渲染出表单', true)

  // ── C2 选工单（ZiwiSelect 浮层，不是原生 select）──
  await page.click('.ziwi-select__field')
  await page.waitForSelector('.ziwi-select-panel', { timeout: 10000 })
  // 选项里有搜索框就先用它收窄，避免滚一长串
  const search = await page.$('.ziwi-select-panel__search input')
  if (search) await search.fill(wo.woNo)
  const opt = page.locator('.ziwi-select-panel').getByText(wo.woNo, { exact: false }).first()
  await opt.click({ timeout: 10000 })
  // 关掉浮层（有的变体选完不自动关）
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(300)

  // ── C3 填工序编码 + 合格数量 ──
  // ★ 工序编码必须填**赋码节点**（字典 trace_code_node 配的 CW010），
  //   填别的工序不会出码 —— 这正是"节点是数据"的界面表现。
  await page.fill(fieldInput('工序编码'), 'CW010')
  await page.fill(fieldInput('合格数量'), '2')
  await page.fill(fieldInput('投入数量'), '2')

  // ── C4 提交，等赋码弹窗 ──
  await page.click('.wrf-submit button')
  let dialogText = ''
  try {
    await page.waitForSelector('.van-dialog', { timeout: 20000 })
    dialogText = await page.$eval('.van-dialog', (el) => el.innerText)
  } catch (e) {
    dialogText = ''
  }

  chk('C2 提交后弹出赋码提示', /已生成\s*2\s*个部件码/.test(dialogText),
    dialogText ? dialogText.replace(/\n/g, ' | ').slice(0, 160)
               : '没等到弹窗 —— 多半是赋码节点字典没灌（见文件头说明）')

  const codes = (dialogText.match(/TD-\d{8}-\d{4,}/g) || [])
  chk('C3 弹窗里是 2 个 TD-YYYYMMDD-流水号', codes.length === 2, codes.join(', '))
  chk('C3b 两串码的流水号连续',
    codes.length === 2 && Number(codes[1].split('-').pop()) === Number(codes[0].split('-').pop()) + 1,
    codes.join(' → '))

  chk('C4 无 JS 错误', pageErr.length === 0, pageErr.slice(0, 3).join(' | '))

  await browser.close()
  console.log(`\n通 ${passed} / 断 ${fails.length}`)
  if (fails.length) { console.log('失败项：'); fails.forEach((f) => console.log('  - ' + f)) }
  process.exit(0)
})()
