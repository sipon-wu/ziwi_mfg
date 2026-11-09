// 批次码标签（C-97）· 浏览器级验收
//
// 跑法（先 `DIST_DIR=frontend/dist_<本次构建> PORT=5189 node scripts/serve_alpha.js`）：
//   BASE_URL=http://127.0.0.1:5189 node e2e/browser_test/_probe_batch_label.js
//
// 断四件事：
//   A. 批次列表每行有「标签」入口，且显示了**码级别中文**（原料码/部件码/成品码）
//   B. 点「标签」→ 真正落到打印预览页，PDF 字节出来（blob:），标题是「追溯码标签」
//   C. 预览页必须给出「实际大小 / 100%」提示 —— 标签缩放后二维码扫不出来
//   D. 负向：不存在的批次 id → 页面显示失败文案，不是白屏、不是永久 loading
//
// ★ 为什么 A3 要单独断「码级别是中文」：
//   界面不许裸渲染枚举是项目铁律。这里最容易犯的错是把 `batch_type` 直接
//   `{{ item.batch_type }}` 印出去，页面上就是 raw / wip / final 三个英文，
//   而且**看起来像正常显示**，没人会去修。
//
// ★ 为什么 B 要断 blob: 而不是断"页面有内容"：
//   预览页在失败时也是有内容的（失败卡片）。只看"有内容"会把 404 当成功。
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5189'
const TENANT = process.env.E2E_TENANT || 'MFG1'
const USER = process.env.E2E_USER || 'mfg_admin'
const PWD = process.env.E2E_PWD || 'admin123'

const KIND_LABELS = ['原料码', '部件码', '成品码']

const fails = []
const skips = []
let passed = 0
const ok = (n, d = '') => { passed += 1; console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`) }
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const skip = (n, why) => { skips.push(`${n} · ${why}`); console.log(`  [SKIP] ${n} · ${why}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

async function login(page) {
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.clear())
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', USER)
  await page.fill('input[type="password"]', PWD)
  const t = await page.$('input[name="tenant_id"], input[name="tenant"]')
  if (t) await t.fill(TENANT)
  await page.click('button[type="submit"]')
  try {
    await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 15000 })
    return true
  } catch {
    return false
  }
}

/** 等列表出现真实数据行（不是骨架、不是空态）。
 *
 * ★ 不能只等 `.van-cell > 0`：首屏渲染是渐进的，第一个 cell 落地时后面还没渲染，
 *   于是就按"1 行"去统计按钮数和码级别 → A2/A3 双双假红（2026-11-09 实测踩过）。
 *   判据改成等**本轮真正关心的那个元素**（码级别标记）出现。
 */
async function waitRows(page) {
  try {
    await page.waitForFunction(
      () => document.querySelectorAll('.van-cell .batch-kind').length > 0, { timeout: 15000 })
    await page.waitForTimeout(300)   // 同批渲染的其余行落地
    return true
  } catch {
    return false
  }
}

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const consoleErrors = []
  page.on('pageerror', (e) => consoleErrors.push(String(e)))

  // ── A0 登录 ───────────────────────────────────────────────
  console.log('\n== A0 登录 ==')
  if (!(await login(page))) {
    bad('A0', '登录失败，后续全部无法验证')
    console.log(`\n通 ${passed} / 断 ${fails.length} / 跳过 ${skips.length}`)
    await browser.close()
    process.exit(1)
  }
  ok('A0', `${USER}@${TENANT}`)

  // ── A 批次列表：入口 + 码级别 ─────────────────────────────
  console.log('\n== A 批次列表 ==')
  await page.goto(`${BASE}/#/wms/batches`, { waitUntil: 'domcontentloaded' })
  const hasRows = await waitRows(page)
  if (!hasRows) {
    bad('A1', '批次列表没有任何数据行（空态或加载失败）')
  } else {
    // ★ 行数以「码级别标记」为准，不是 `.van-cell` 计数。
    //   van-list 的「没有更多了」以及 possible 的其它 cell 也会计入 `.van-cell`，
    //   实测就是 21 vs 20 → A2 恒假红。
    const rows = await page.$$eval('.van-cell .batch-kind', (els) => els.length)
    ok('A1', `${rows} 行`)

    // A2：每行都要有「标签」按钮 —— 少一行就少一个能补打的码
    const btns = await page.$$eval('.van-cell .van-button', (els) =>
      els.filter((e) => (e.innerText || '').includes('标签')).length)
    chk('A2', btns === rows && rows > 0, `「标签」按钮 ${btns} 个 / 行 ${rows} 个`)

    // A3：码级别必须是中文，不能是 raw/wip/final
    const kinds = await page.$$eval('.van-cell .batch-kind', (els) =>
      els.map((e) => (e.innerText || '').trim()))
    const badKinds = kinds.filter((k) => !KIND_LABELS.includes(k))
    if (kinds.length === 0) {
      bad('A3', '行上没有码级别标记（.batch-kind 一个都没有）')
    } else if (badKinds.length) {
      bad('A3', `码级别不是约定文案：${JSON.stringify([...new Set(badKinds)])}`)
    } else {
      ok('A3', `全部 ${kinds.length} 行都是 ${[...new Set(kinds)].join('/')}`)
    }
  }

  // ── B 点「标签」→ 打印预览 ────────────────────────────────
  console.log('\n== B 打印预览 ==')
  if (hasRows) {
    await page.click('.van-cell .van-button')
    try {
      await page.waitForFunction(
        (p) => location.hash.includes(p), '/print/preview/batch/', { timeout: 15000 })
      ok('B1', page.url().split('#')[1])
    } catch {
      bad('B1', `没跳到打印预览，当前 ${page.url().split('#')[1]}`)
    }

    const h = page.url().split('#')[1] || ''
    chk('B2', h.includes('paper=label80'),
      `纸型必须是 label80（贴实物），实际 ${h.includes('paper=') ? h.split('paper=')[1] : '未带 paper'}`)

    // B3：PDF 真出来了 —— iframe 或 object 的 src 是 blob:
    let blobOk = false
    try {
      await page.waitForFunction(() => {
        const f = document.querySelector('iframe.print-page__frame, iframe')
        const o = document.querySelector('object')
        const src = f?.getAttribute('src') || o?.getAttribute('data') || ''
        return src.startsWith('blob:')
      }, { timeout: 20000 })
      blobOk = true
    } catch { /* 下面报红 */ }
    chk('B3', blobOk, blobOk ? '已出 blob PDF' : '预览里没有 blob: PDF 字节流')

    const body = await page.evaluate(() => document.body.innerText || '')
    // ★ chk 的第三个参数是**事实描述**，成功/失败两路共用。
    //   写成"缺 XX"这种只对失败成立的句子，成功时也会原样打出来 → 绿的像红的。
    chk('B4', body.includes('追溯码标签'),
      `正文前 80 字：${body.replace(/\s+/g, ' ').slice(0, 80)}`)
    // C：标签缩放提醒必须在点打印之前就看得见
    chk('B5', body.includes('实际大小'),
      body.includes('实际大小') ? '有缩放提示' : '缺「实际大小 / 100%」提示（缩放会让二维码扫不出来）')
  } else {
    skip('B1-B5', '列表无数据，无法点标签')
  }

  // ── D 负向：不存在的批次 ─────────────────────────────────
  console.log('\n== D 负向 ==')
  await page.goto(`${BASE}/#/print/preview/batch/999999?paper=label80`,
    { waitUntil: 'domcontentloaded' })
  // ★ 等"事实"而不是等时间：同路由只换参数时组件是复用的，
  //   上一张纸还在屏幕上停留一小会儿 —— 固定 sleep 会把"还没重载"判成"没重载"。
  let dFailed = false
  try {
    await page.waitForFunction(
      () => /不存在|失败|错误/.test(document.body.innerText || ''), { timeout: 15000 })
    dFailed = true
  } catch { /* 下面报红 */ }

  const dbody = await page.evaluate(() => document.body.innerText || '')
  chk('D1', dFailed, `正文：${dbody.replace(/\s+/g, ' ').slice(0, 120)}`)
  const dHasBlob = await page.evaluate(() => {
    const f = document.querySelector('iframe.print-page__frame, iframe')
    return (f?.getAttribute('src') || '').startsWith('blob:')
  })
  chk('D2', !dHasBlob, dHasBlob ? '不存在的批次居然出 PDF 了' : '未出 PDF（对）')

  // ── 收尾 ─────────────────────────────────────────────────
  if (consoleErrors.length) {
    console.log(`\n[note] 页面 JS 异常 ${consoleErrors.length} 条（仅供参考，不计失败）：`)
    consoleErrors.slice(0, 3).forEach((e) => console.log('   ' + e.slice(0, 160)))
  }

  await page.screenshot({ path: '/tmp/_batch_label_probe.png', fullPage: false }).catch(() => {})
  await browser.close()

  console.log(`\n通 ${passed} / 断 ${fails.length} / 跳过 ${skips.length}`)
  // ★ 退出码必须带红：原来恒 exit(0)，探针红了 CI 也绿
  process.exit(fails.length ? 1 : 0)
})()
