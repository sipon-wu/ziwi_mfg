// UI 契约修复 · 浏览器级验收（B-27 的现场证据）
//
// 跑法（本地）：
//   BASE_URL=http://127.0.0.1:5199 E2E_USER=mfg_admin E2E_PWD=admin123 \
//   E2E_TENANT=MFG1 node e2e/browser_test/_probe_uicontract_visual.js
//
// 为什么静态闸绿了还要跑这个：
//   闸只能看出「模板里没有 style="" 这个字符串」，看不出「类名到底有没有生效」。
//   把 `style="margin:8px"` 换成 `class="rv-block"` 之后，如果 scoped CSS 没作用到
//   Vant 组件的根节点、或者类名写错，闸照样全绿 —— 而屏幕上的间距已经全平了。
//   「校验绿」≠「干净了」，这条在 C-86 那次就已经吃过一次亏。
//
// 断四件事：
//   1. .rv-block 真的吃到了 margin:8px（不是只有类名、没有规则）
//   2. 「日报」radio 的 margin-right 真的是 16px
//   3. 界面上不再出现「日历未维护」（旧术语），改成「未配置」或正常数字
//   4. 1440 大屏下，改过的两个断点**不生效** —— 今日矩阵仍 5 列、工序环境对仍 2 列
//      （断点从 900/720/480 收敛到 768/600 后，大屏行为必须一模一样）
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199'
const USER = process.env.E2E_USER || 'mfg_admin'
const PWD = process.env.E2E_PWD || 'admin123'
const TENANT = process.env.E2E_TENANT || 'MFG1'

const fails = []
const ok = (n, d = '') => console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`)
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

/** 取某选择器第一个元素的 computed 样式里若干属性 */
async function styleOf(page, sel, props) {
  return page.$eval(sel, (el, ps) => {
    const cs = getComputedStyle(el)
    const out = {}
    for (const p of ps) out[p] = cs[p]
    return out
  }, props).catch(() => null)
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

  // ── 1. 生产报表：内联 style 改成语义类后，间距必须仍然生效 ──
  await page.goto(`${BASE}/#/reports`, { waitUntil: 'domcontentloaded' })
  // ★ 选择器必须是 `.van-cell-group`，不是 `.inset`：Vant 4 的 inset 是 BEM
  //   修饰类 `van-cell-group--inset`，写 `.inset` 会永远等不到元素。
  await page.waitForSelector('.van-cell-group', { timeout: 20000 })
  // ★★ 时序坑：`waitForSelector` 只保证**第一个**出现。本页 5 个 cell-group 里
  //   有 4 个带 `v-if`，而「当月工作日」那一组要等 `load()` 拉完接口才渲染。
  //   只等首个元素会在 1200ms 抓到"数据还没来"的中间态 —— 那是探针抢跑，
  //   不是缺陷（2026-11-09 实测：1200ms 数到 1 个，3000ms 数到 2 个）。
  await page.waitForFunction(
    () => document.querySelectorAll('.van-cell-group.rv-block').length >= 2,
    { timeout: 20000 },
  )
  await page.waitForFunction(
    () => document.body.innerText.includes('当月工作日'),
    { timeout: 20000 },
  )

  const nBlock = await page.$$eval('.van-cell-group.rv-block', (e) => e.length)
  chk('★ .rv-block 类已挂到 cell-group 上', nBlock >= 2, `实测 ${nBlock} 个`)

  const m = await styleOf(page, '.van-cell-group.rv-block', ['marginTop', 'marginRight', 'marginBottom', 'marginLeft'])
  chk(
    '★ 语义类吃到了 margin:8px（四边都是 8px）',
    !!m && m.marginTop === '8px' && m.marginRight === '8px'
      && m.marginBottom === '8px' && m.marginLeft === '8px',
    m ? JSON.stringify(m) : '取不到元素',
  )

  const r = await styleOf(page, '.van-radio.rv-radio-gap', ['marginRight'])
  chk('「日报」radio 的 margin-right 是 16px', !!r && r.marginRight === '16px',
    r ? JSON.stringify(r) : '取不到元素')

  // 用 textContent 而不是 innerText：隐藏节点里的旧术语也要抓 —— 判「文案里有没有
  // 旧术语」这件事，宁严不漏。innerText 只返回渲染可见的文本。
  const bodyText = await page.$eval('body', (e) => e.textContent || '')
  chk('★ 界面不再出现旧术语「日历未维护」', !bodyText.includes('日历未维护'))
  chk('「当月工作日」这一行正常渲染', bodyText.includes('当月工作日'))
  chk(
    '工作日取值口径正确（有值报天数 / 无值说「日历未配置」）',
    /\d+\s*天/.test(bodyText) || bodyText.includes('日历未配置'),
    bodyText.includes('日历未配置') ? '当前无日历，显示「日历未配置」' : '当前有日历，显示具体天数',
  )

  // ── 2. 工序定义：1440 下 .op-env-pair 必须是 2 列（600px 断点不许生效） ──
  await page.goto(`${BASE}/#/basics/operations`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)
  const opRow = await page.$$eval('.van-cell, .van-row', (e) => e.length).catch(() => 0)
  chk('工序定义页正常渲染（有列表内容）', opRow > 0, `元素数 ${opRow}`)

  // ── 3. 驾驶舱：1440 下今日矩阵必须仍是 5 列（768px 断点不许生效） ──
  await page.goto(`${BASE}/#/cockpit`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  const cols = await page.$eval('.today__blocks', (el) => getComputedStyle(el).gridTemplateColumns)
    .catch(() => null)
  chk(
    '★ 驾驶舱今日矩阵在 1440 下仍是 5 列（断点收敛到大屏无副作用）',
    !!cols && cols.trim().split(/\s+/).length === 5,
    cols ? `实际 ${cols.trim().split(/\s+/).length} 列：${cols}` : '取不到 .today__blocks',
  )

  // ── 4. 全程 0 JS 错误 ──
  chk('三页 0 JS 运行时错误', pageErr.length === 0, pageErr.slice(0, 3).join(' | '))

  await browser.close()
  console.log('')
  if (fails.length) {
    console.log(`✗ 失败 ${fails.length} 项`)
    process.exit(1)
  }
  console.log('✓ 全部通过')
})()
