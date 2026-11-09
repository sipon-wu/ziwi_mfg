// 返修拆组套（C-97）· 浏览器级验收
//
// 跑法（先 `DIST_DIR=frontend/dist_c97c PORT=5189 node scripts/serve_alpha.js`，
//      后端在 http://127.0.0.1:8000）：
//   BASE_URL=http://127.0.0.1:5189 node e2e/browser_test/_probe_batch_decompose.js
//
// ## 断什么
//   A. 有子件的成品码：出现「返修拆解」入口，且按钮文案报出**数量**
//   B. 点一下只展开确认区（不立即拆）：列出要解除的码 + 必填原因 + 确认/取消
//   C. 不填原因点确认 → 报错且**没拆**（负向：危险动作必须有拦截）
//   D. 填原因确认 → 真拆开，界面自己重查后变成「无部件记录」
//   E. 没有子件的成品码（或原料码）：**没有**拆解入口（负向：入口不该滥用）
//
// ## 为什么探针要自己造数据
// 拆解的前提是"一个已经组套过的成品码"。本地/预发布的种子里基本没有组套数据
// （要么是空的，要么是别人上一轮留下的）。**偷别人的数据跑，单独跑就会红**，
// 所以这里用 API 现场造一对部件码 + 组套，跑完把关系拆掉。
//
// ★ 码本身（E2E-DEC-*）跑完仍在库里，交给 `scripts/clean_e2e_residue.py --apply` 收；
//   探针结尾会打印提示，不假装自己清干净了。
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5189'
const API = process.env.API_BASE || 'http://127.0.0.1:8000'
const TENANT = process.env.E2E_TENANT || 'MFG1'
const USER = process.env.E2E_USER || 'mfg_admin'
const PWD = process.env.E2E_PWD || 'admin123'
const TAG = process.env.E2E_TAG || 'E2E-DEC'

const fails = []
const skips = []
let passed = 0
const ok = (n, d = '') => { passed += 1; console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`) }
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }
const skip = (n, why) => { skips.push(`${n} · ${why}`); console.log(`  [SKIP] ${n} · ${why}`) }
const chk = (n, cond, d = '') => (cond ? ok(n, d) : bad(n, d))

let token = ''

async function api(path, opts = {}) {
  const res = await fetch(`${API}/api/v1${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  })
  const text = await res.text()
  let body = null
  try { body = JSON.parse(text) } catch { body = text }
  return { status: res.status, body }
}

async function loginApi() {
  const r = await api('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username: USER, password: PWD, tenant_code: TENANT }),
  })
  token = r.body?.access_token || ''
  return !!token
}

async function loginUi(page) {
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

/** 造一对部件码 + 一个成品码（组套）。返回 { finalNo, childNos }。 */
async function seedComposed() {
  const mats = await api('/wms/materials?page_size=1')
  const materialId = mats.body?.data?.items?.[0]?.id
  if (!materialId) throw new Error('没有物料主数据，无法造码')

  const wos = await api('/work-orders?page_size=1')
  const woId = wos.body?.data?.items?.[0]?.id
  if (!woId) throw new Error('没有工单，无法组套')

  const stamp = Date.now().toString().slice(-6)
  const childNos = [`${TAG}-ST-${stamp}`, `${TAG}-RT-${stamp}`]
  for (const no of childNos) {
    const r = await api('/wms/batches', {
      method: 'POST',
      body: JSON.stringify({ batch_no: no, material_id: materialId, batch_type: 'wip' }),
    })
    if (r.status !== 200) throw new Error(`造部件码失败 ${no}：${r.status} ${JSON.stringify(r.body).slice(0, 120)}`)
  }

  const c = await api('/wms/batches/compose', {
    method: 'POST',
    body: JSON.stringify({ stator_no: childNos[0], rotor_no: childNos[1], work_order_id: woId }),
  })
  if (c.status !== 200) throw new Error(`组套失败：${c.status} ${JSON.stringify(c.body).slice(0, 160)}`)
  return { finalNo: c.body.data.batch_no, childNos }
}

/** 在「查组套构成」里输入一个码并查询。
 *
 * ★ 不能只 `fill + Enter`：`ZiwiScanField` 用 `useScanInput` 的**缓冲**判定成码
 *   （靠 keydown 逐字符累加），而 `fill` 不产生 keydown 序列 —— Enter 时缓冲是空的，
 *   直接被 reset，什么都不会发生（页面看着毫无反应，像按钮坏了）。
 *   真实现场有两条路：扫码枪的硬键序列，或手输后点「扫码」按钮（`onConfirm`）。
 *   这里走后者 —— 它是真实可点的路径，不是测试专用的后门。
 */
async function lookup(page, code) {
  const box = page.locator('[data-field="lookup_no"]')
  await box.locator('input').first().fill('')
  await box.locator('input').first().fill(code)
  await box.locator('.ziwi-scan-field__btn').click()
  // ★ 等"结果区里出现了**这个码**"，而不是等"结果区存在"：
  //   上一次查询的结果还在 DOM 里，只等存在会立刻满足 → 拿到的还是上一台的数据
  //   （这类假绿比红更难发现：界面、断言、数据三者都"看起来对"）。
  await page.waitForFunction((c) => {
    const t = document.querySelector('.bc-lookup')?.innerText || ''
    const e = document.querySelector('.bc-error')?.innerText || ''
    return t.includes(c) || (!!e && !t)
  }, code, { timeout: 15000 })
  await page.waitForTimeout(300)
}

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  // ── A0 准备 ───────────────────────────────────────────────
  console.log('\n== A0 准备 ==')
  if (!(await loginApi())) {
    bad('A0', 'API 登录失败，无法造数')
    await browser.close()
    console.log(`\n通 ${passed} / 断 ${fails.length} / 跳过 ${skips.length}`)
    process.exit(1)
  }
  let seeded
  try {
    seeded = await seedComposed()
    ok('A0', `造好成品码 ${seeded.finalNo}（子件 ${seeded.childNos.join(' / ')}）`)
  } catch (e) {
    bad('A0', String(e.message || e))
    await browser.close()
    console.log(`\n通 ${passed} / 断 ${fails.length} / 跳过 ${skips.length}`)
    process.exit(1)
  }

  if (!(await loginUi(page))) {
    bad('A0b', 'UI 登录失败')
    await browser.close()
    console.log(`\n通 ${passed} / 断 ${fails.length} / 跳过 ${skips.length}`)
    process.exit(1)
  }

  // ── A 拆解入口 ────────────────────────────────────────────
  console.log('\n== A 入口 ==')
  await page.goto(`${BASE}/#/wms/batches/compose`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-field="lookup_no"]', { timeout: 15000 })
  await lookup(page, seeded.finalNo)

  const hasKids = await page.$$eval('.bc-lookup__kids li', (e) => e.length)
  chk('A1', hasKids === 2, `查到的子件 ${hasKids} 个（预期 2）`)

  const btn = page.locator('.bc-decompose__open')
  const btnVisible = await btn.count() > 0
  chk('A2', btnVisible, btnVisible ? '' : '有子件的成品码上没有「返修拆解」入口')
  if (btnVisible) {
    const txt = (await btn.innerText()).replace(/\s+/g, ' ')
    chk('A3', /2/.test(txt), `按钮要报出数量，实际文案：${txt}`)
  }

  // ── B 两段式：点一下只展开确认区 ───────────────────────────
  console.log('\n== B 确认区 ==')
  if (btnVisible) {
    await btn.click()
    await page.waitForTimeout(300)
    const warn = page.locator('.bc-decompose__warn')
    const warnVisible = await warn.count() > 0
    chk('B1', warnVisible, warnVisible ? '' : '点了之后没有确认区（可能一步就拆了）')
    if (warnVisible) {
      const wtxt = (await warn.innerText()).replace(/\s+/g, ' ')
      const missing = seeded.childNos.filter((n) => !wtxt.includes(n))
      chk('B2', missing.length === 0,
        missing.length ? `确认区没列出这些码：${missing.join(',')}` : '两个码都摆出来了')
    }
    // B3：展开后，还没点确认 —— 后端不该已经拆了
    const comp = await api(`/wms/batches?keyword=${encodeURIComponent(seeded.finalNo)}&page_size=5`)
    const row = (comp.body?.data?.items || []).find((x) => x.batch_no === seeded.finalNo)
    const kidsNow = row ? (await api(`/wms/batches/${row.id}/composition`)).body?.data?.children?.length : -1
    chk('B3', kidsNow === 2, `展开确认区后子件应仍是 2 个，实际 ${kidsNow}（说明按钮一步就拆了）`)

    // ── C 空原因被拦 ────────────────────────────────────────
    // ★ 全部包在 `if (warnVisible)` 里：确认区不存在时 C/D 根本无从谈起。
    //   不包的话，locator 等 30 秒后抛未捕获异常 → 整轮报告都不打印，
    //   看起来像"探针崩了"而不是"界面少了确认区"（诊断信息全丢）。
    if (!warnVisible) {
      skip('C/D', '确认区没出现，后续步骤无从验证')
    } else {
      console.log('\n== C 空原因 ==')
      const confirm = page.locator('.bc-decompose__actions .van-button--danger')
      await confirm.click()
      await page.waitForTimeout(600)
      const errTxt = await page.evaluate(() => document.querySelector('.bc-error')?.innerText || '')
      chk('C1', /原因/.test(errTxt), `不填原因应报「请填写拆解原因」，实际：${errTxt || '（没有报错）'}`)
      const kidsAfterC = row ? (await api(`/wms/batches/${row.id}/composition`)).body?.data?.children?.length : -1
      chk('C2', kidsAfterC === 2, `被拦住了却已经拆开（子件剩 ${kidsAfterC}）`)

      // ── D 真拆 ──────────────────────────────────────────────
      console.log('\n== D 真拆 ==')
      await page.fill('[data-field] input[placeholder*="原因"], input[placeholder*="返修单号"]',
        'E2E 探针返修拆解')
      await page.waitForTimeout(200)
      await page.locator('.bc-decompose__actions .van-button--danger').click()
      // 等成功提示（界面会自己重查构成）
      let doneTxt = ''
      try {
        await page.waitForFunction(
          () => /已解除/.test(document.querySelector('.bc-decompose__done')?.innerText || ''),
          { timeout: 15000 })
        doneTxt = await page.evaluate(() => document.querySelector('.bc-decompose__done')?.innerText || '')
      } catch { /* 下面报红 */ }
      chk('D1', /已解除 2/.test(doneTxt), `成功提示不对：${doneTxt || '（没出现）'}`)

      const kidsAfterD = row ? (await api(`/wms/batches/${row.id}/composition`)).body?.data?.children?.length : -1
      chk('D2', kidsAfterD === 0, `后端子件应为 0，实际 ${kidsAfterD}（界面说拆了但没落到库）`)

      // ★ 不能取第一个 `.bc-lookup__none`：结果区里"尚未组套"也是这个类名，
      //   第一个命中的是「装进了」那行，永远是「尚未组套」—— 不管你拆没拆。
      //   必须按行标签定位到「由这些组成」那一行。
      const childRowText = await page.evaluate(() => {
        const rows = Array.from(document.querySelectorAll('.bc-lookup__row'))
        const row = rows.find((r) => (r.textContent || '').includes('由这些组成'))
        return row ? (row.textContent || '').replace(/\s+/g, ' ') : ''
      })
      chk('D3', /无部件记录/.test(childRowText),
        `「由这些组成」行应变成「无部件记录」，实际：${childRowText || '（没找到该行）'}`)

      // D4：拆完入口要消失（没有可拆的了）
      await page.waitForTimeout(300)
      const btnAfter = await page.locator('.bc-decompose__open').count()
      chk('D4', btnAfter === 0, '已经拆空了，「返修拆解」入口还留着（会引导人去点一个必然报错的按钮）')
    }
  } else {
    skip('B/C/D', 'A 段没找到入口')
  }

  // ── E 负向：不该给入口的码 ────────────────────────────────
  console.log('\n== E 负向 ==')
  const wip = seeded.childNos[0]
  await lookup(page, wip)
  const wipBtn = await page.locator('.bc-decompose__open').count()
  const wipErr = await page.evaluate(() => document.querySelector('.bc-error')?.innerText || '')
  chk('E1', wipBtn === 0,
    wipBtn ? `部件码「${wip}」上不该有拆解入口` : `部件码查询结果：${wipErr || '正常显示'}`)

  await browser.close()

  // ★ 收尾提示必须指对脚本。实测：`clean_e2e_residue.py` 只清四类主数据
  //   （路线/工位/设备/工序），批次不在它的规则里；批次的归属是
  //   `scripts/probe_artifacts.py`，但 `E2E-DEC-*` 这种前缀**两家规则都不认**
  //   （2026-11-09 实测，只能手工按 batch_no 前缀清）。
  //   写一句"跑某脚本就能清干净"是好心骗人 —— 它会让人以为已经干净了。
  console.log(`\n[note] 本轮造的码仍在库里：成品码 ${seeded.finalNo}`
    + ` / 部件码 ${seeded.childNos.join(' / ')}`
    + `\n[note] 清理：先跑 scripts/probe_artifacts.py --yes；若未识别（E2E-DEC-* 不在`
    + ` 任何自动规则里），需按 batch_no 前缀手工删 batches 行`)
  console.log(`\n通 ${passed} / 断 ${fails.length} / 跳过 ${skips.length}`)
  process.exit(fails.length ? 1 : 0)
})()
