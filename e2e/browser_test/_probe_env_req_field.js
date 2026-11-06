/**
 * 探针：工序页「洁净度」列 + 「环境要求（环）」录入区是否真的可用。
 *
 * 要证明三件事（缺一不可）：
 *   1. 列表真有「洁净度」列，且渲染的是中文「十万级（ISO 8）」而不是 `iso8`；
 *   2. 表单里真有洁净度/温湿度录入控件（上一版只有类型声明 + `env_req: null`，
 *      字段躺着三周，全库 0 条有值）；
 *   3. 填完保存 → 列表立刻显示、行展开显示成一句话而不是 JSON。
 *
 * 跑法（须 vite dev 在 5173、后端在 8000）：
 *   node e2e/browser_test/_probe_env_req_field.js
 *
 * 自建自清：末尾用 API 把探针工序删掉，不留数据给产能闸。
 */
const { chromium } = require('@playwright/test')
const path = require('path')
const fs = require('fs')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_BASE || 'http://127.0.0.1:8000/api/v1'
const TENANT = process.env.E2E_TENANT || 'mfg_demo'
const SHOT_DIR = path.join(__dirname, 'screenshots', 'env_req')
const CODE = `OP-ENVUI-${Date.now().toString().slice(-9)}`

const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? ' · ' + detail : ''}`)
}

;(async () => {
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  // ── 登录 ──────────────────────────────────────────────
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', 'mfg_admin')
  await page.fill('input[type="password"]', 'admin123')
  const tenantInput = page.locator('input[name="tenant"], input[name="tenant_id"]')
  if (await tenantInput.count()) await tenantInput.fill(TENANT)
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })

  // ── 1. 列表：洁净度列存在 ─────────────────────────────
  await page.goto(`${BASE}/#/basics/operations`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  const headers = await page.$$eval('.op-table thead th', (ths) =>
    ths.map((t) => t.textContent.trim()),
  )
  check('列表有「洁净度」列', headers.includes('洁净度'), headers.join('|'))
  await page.screenshot({ path: path.join(SHOT_DIR, 'L1_list.png'), fullPage: false })

  // ── 2. 表单：录入控件存在 ─────────────────────────────
  await page.click('button:has-text("新增工序")')
  await page.waitForTimeout(700)
  const sheet = page.locator('.ziwi-sheet:visible').last()
  const formText = await sheet.innerText()
  check('表单有「洁净度等级」', formText.includes('洁净度等级'))
  check('表单有温度上下限', formText.includes('温度下限') && formText.includes('温度上限'))
  check('表单有湿度上下限', formText.includes('湿度下限') && formText.includes('湿度上限'))
  await page.screenshot({ path: path.join(SHOT_DIR, 'L2_form_empty.png'), fullPage: false })

  // ── 3. 填表并保存 ────────────────────────────────────
  // 编码/名称是纯文本 van-field，按 label 定位
  // 按 label 定位字段。不能用 `:has(:text-is(...))` —— Playwright 的 `:text-is()`
  // 只允许出现在选择器最内层，套进 `:has()` 里会静默匹配 0 个然后超时。
  const fieldByLabel = (label) =>
    sheet.locator('.van-field').filter({ has: page.getByText(label, { exact: true }) })
  const fillByLabel = async (label, value) => {
    await fieldByLabel(label).first().locator('input').first().fill(String(value))
  }
  await fillByLabel('工序编码', CODE)
  await fillByLabel('工序名称', '洁净度界面探针')
  // 洁净度：点开 ZiwiSelect（W 档就地展开），选「十万级（ISO 8）」
  const levelField = fieldByLabel('洁净度等级').first().locator('.ziwi-select')
  check('洁净度是可选控件（不是只读文本）', (await levelField.count()) > 0)
  if (await levelField.count()) {
    await levelField.first().click()
    await page.waitForTimeout(500)
    await page.locator('.ziwi-select-list__row:has-text("十万级")').first().click()
    await page.waitForTimeout(300)
  }
  await fillByLabel('温度下限', 20)
  await fillByLabel('温度上限', 26)
  await fillByLabel('湿度下限', 45)
  await fillByLabel('湿度上限', 60)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(SHOT_DIR, 'L3_form_filled.png'), fullPage: false })

  await page.click('.ziwi-sheet__btn--primary')
  await page.waitForTimeout(2000)

  // ── 4. 列表回显：中文标签而非原码 ────────────────────
  const row = page.locator(`tr:has(td:text-is("${CODE}"))`).first()
  check('新建的工序出现在列表', (await row.count()) > 0)
  const rowText = (await row.count()) ? await row.innerText() : ''
  check('洁净度渲染成中文标签', rowText.includes('十万级'), rowText.replace(/\n/g, ' '))
  check('洁净度没有裸渲染原码', !/iso8/i.test(rowText), rowText.replace(/\n/g, ' '))
  await page.screenshot({ path: path.join(SHOT_DIR, 'L4_row_with_clean_level.png'), fullPage: false })

  // ── 5. 行展开：环境要求是一句话，不是 JSON ───────────
  if (await row.count()) await row.click()
  await page.waitForTimeout(900)
  const detailText = await page.locator('.row-detail').first().innerText().catch(() => '')
  check('行展开显示中文环境要求',
    detailText.includes('十万级') && detailText.includes('温度') && detailText.includes('湿度'),
    detailText.replace(/\n/g, ' ').slice(0, 160))
  // 精确到「环境要求」那一格：整段 innerText 里也含"温度"两个字（字段名），
  // 光用 includes 会被字段名蒙过，必须按 rd-cell 逐格取 label→value。
  const envCell = await page.evaluate(() => {
    const cells = [...document.querySelectorAll('.row-detail .rd-cell')]
    const hit = cells.find((c) => (c.querySelector('.rd-label')?.textContent || '').startsWith('环境要求'))
    return hit
      ? {
          label: hit.querySelector('.rd-label').textContent.trim(),
          value: hit.querySelector('.rd-value').textContent.trim(),
        }
      : null
  })
  check('行展开有「环境要求」独立格', !!envCell, envCell ? envCell.label : '未找到')
  check('环境要求渲染成一句话（洁净度+温度+湿度）',
    !!envCell && envCell.value.includes('十万级') && envCell.value.includes('20~26℃')
      && envCell.value.includes('45~60%RH'),
    envCell ? envCell.value : '')
  check('行展开没有吐 JSON', !detailText.includes('"clean_level"'),
    detailText.replace(/\n/g, ' ').slice(0, 120))
  await page.screenshot({ path: path.join(SHOT_DIR, 'L5_row_detail.png'), fullPage: false })

  // ── 6. 收尾：删掉探针工序 ────────────────────────────
  const login = await page.request.post(`${API}/auth/login`, {
    data: { username: 'mfg_admin', password: 'admin123', tenant_id: TENANT },
  })
  const token = (await login.json()).access_token
  const hdr = { Authorization: `Bearer ${token}`, 'X-Tenant-Id': TENANT }
  const found = await page.request.get(`${API}/operations?page=1&page_size=50&keyword=${CODE}`, { headers: hdr })
  const items = (await found.json()).data.items || []
  for (const it of items) {
    await page.request.delete(`${API}/operations/${it.id}`, { headers: hdr })
  }
  const after = await page.request.get(`${API}/operations?page=1&page_size=50&keyword=${CODE}`, { headers: hdr })
  check('探针工序已清理', (await after.json()).data.total === 0)

  await browser.close()
  const failed = results.filter((r) => !r.ok)
  console.log(`\n${results.length - failed.length} PASS / ${failed.length} FAIL`)
  fs.writeFileSync(
    path.join(SHOT_DIR, 'result.json'),
    JSON.stringify({ when: new Date().toISOString(), code: CODE, results }, null, 2),
  )
  process.exit(failed.length ? 1 : 0)
})().catch((e) => {
  console.error('[FATAL]', e.message)
  process.exit(2)
})
