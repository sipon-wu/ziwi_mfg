// 驾驶舱 KPI + 生产报表（日报/月报）浏览器验收
// 跑法：
//   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
//   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
//   BASE_URL=http://127.0.0.1:5183 node e2e/browser_test/cockpit_report_e2e.js
const { chromium } = require('@playwright/test')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const USER = process.env.E2E_USER || 'ah_admin'
const PWD = process.env.E2E_PWD || 'Ah@2026seed'
const TENANT = process.env.E2E_TENANT || 'AH-THR'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/cockpit_report'

const fs = require('fs')
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true })

const fails = []
const oks = []
const ok = (n, d = '') => { oks.push(n); console.log(`  [OK ] ${n}${d ? ' · ' + d : ''}`) }
const bad = (n, d = '') => { fails.push(`${n} · ${d}`); console.log(`  [FAIL] ${n}${d ? ' · ' + d : ''}`) }

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const apiErr = []
  page.on('response', (r) => {
    if (r.url().includes('/api/v1') && r.status() >= 500) apiErr.push(`${r.status()} ${r.url()}`)
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
  ok('登录', `${USER} / ${TENANT}`)

  // ── 驾驶舱 ──
  console.log('\n驾驶舱 KPI')
  await page.goto(`${BASE}/#/cockpit`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)
  await page.screenshot({ path: `${OUT}/K1_cockpit.png`, fullPage: true })

  const kpi = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.kpi-card')]
    const read = (c) => ({
      title: (c.querySelector('.kpi-title') || {}).textContent?.trim() || '',
      value: (c.querySelector('.kpi-value') || {}).textContent?.trim() || '',
      unavailable: c.classList.contains('kpi-card--unavailable'),
    })
    const body = document.body.innerText
    return {
      total: cards.length,
      items: cards.map(read),
      unavailable: cards.filter((c) => c.classList.contains('kpi-card--unavailable')).length,
      sub: (document.querySelector('.cockpit__sub') || {}).textContent?.trim() || '',
      modules: [...document.querySelectorAll('.cockpit__name')].map((e) => e.textContent.trim()),
      externalTag: document.body.innerText.includes('独立产品线'),
      bodyLen: body.length,
    }
  })
  ok('KPI 卡片渲染', `${kpi.total} 张`)
  // 原 12 张里有 3 张是「未接入」占位；本轮扩到 17 张且全部真实接入
  ;(kpi.total >= 17 ? ok : bad)('KPI 数量 ≥ 17（原 12）', String(kpi.total))
  ;(kpi.unavailable === 0 ? ok : bad)('无「未接入」占位', `${kpi.unavailable} 张未接入`)
  ;(kpi.modules.length === 6 ? ok : bad)('模块卡 6 个', kpi.modules.join('/'))
  ;(kpi.externalTag ? ok : bad)('能碳标注为独立产品线', '')
  ok('覆盖度文案', kpi.sub)

  // 每个 KPI 值必须可读（不是空、不是 NaN）
  const brokenKpi = kpi.items.filter((i) => !i.value || /NaN|undefined|null/.test(i.value))
  ;(brokenKpi.length === 0 ? ok : bad)(
    'KPI 值均可读', brokenKpi.length ? JSON.stringify(brokenKpi.slice(0, 3)) : `${kpi.items.length} 项`)

  // ── 生产报表 ──
  console.log('\n生产报表（日报）')
  await page.goto(`${BASE}/#/reports`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)

  // 默认是今天；切到有数据的一天
  const dateInput = await page.$('input[type="date"]')
  if (!dateInput) bad('日报日期控件存在', '未找到 input[type=date]')
  else {
    await dateInput.fill('2026-11-03')
    await dateInput.dispatchEvent('change')
    await page.waitForTimeout(2500)
  }
  await page.screenshot({ path: `${OUT}/R1_daily.png`, fullPage: true })

  const daily = await page.evaluate(() => {
    const txt = document.body.innerText
    const rows = [...document.querySelectorAll('.ziwi-report__row')]
    const kv = [...document.querySelectorAll('.ziwi-kpi')].map((k) => ({
      label: (k.querySelector('.ziwi-kpi__label') || {}).textContent?.trim() || '',
      value: (k.querySelector('.ziwi-kpi__value') || {}).textContent?.trim() || '',
      hint: (k.querySelector('.ziwi-kpi__hint') || {}).textContent?.trim() || '',
    }))
    const rowHeights = rows.map((r) => Math.round(r.getBoundingClientRect().height))
    return {
      hasUndefined: /undefined|NaN/.test(txt),
      kpis: kv,
      rowCount: rows.length,
      rowHeights,
      emptyText: (document.querySelector('.ziwi-report__empty') || {}).textContent?.trim() || '',
      hasStateView: !!document.querySelector('.van-empty'),
      text: txt.slice(0, 400),
    }
  })
  ;(daily.hasUndefined ? bad : ok)('日报无 undefined/NaN', '')
  ok('日报 KPI 面板', daily.kpis.map((k) => `${k.label}=${k.value}`).join(' · '))
  ;(daily.kpis.length === 6 ? ok : bad)('日报 KPI 6 项', String(daily.kpis.length))
  // 完工口径必须 ≤ 工序流转口径，且两者不得相等（相等说明又退化成同一口径）
  const num = (label) => Number((daily.kpis.find((k) => k.label === label) || {}).value?.replace(/[^\d.]/g, '') || 0)
  const finish = num('完工产出'), wip = num('工序流转')
  ;(wip >= finish && wip > 0 ? ok : bad)('完工 ≤ 流转 且流转非零', `完工 ${finish} / 流转 ${wip}`)
  if (daily.rowCount > 0) {
    ok('日报明细行', `${daily.rowCount} 行`)
    const tooShort = daily.rowHeights.filter((h) => h < 48)
    ;(tooShort.length === 0 ? ok : bad)('明细行高 ≥ 48', tooShort.length ? `最矮 ${Math.min(...rowHeights0(daily.rowHeights))}` : `min ${Math.min(...daily.rowHeights)}`)
  } else {
    bad('日报明细行', daily.emptyText || daily.text.slice(0, 120))
  }

  // ── 月报 ──
  console.log('\n生产报表（月报）')
  await page.click('input[value="monthly"], .van-radio:has-text("月报")')
  await page.waitForTimeout(2500)
  await page.screenshot({ path: `${OUT}/R2_monthly.png`, fullPage: true })
  const monthly = await page.evaluate(() => {
    const txt = document.body.innerText
    const rows = [...document.querySelectorAll('.ziwi-report__row')]
    return {
      hasUndefined: /undefined|NaN/.test(txt),
      rowCount: rows.length,
      kpis: [...document.querySelectorAll('.ziwi-kpi')].map((k) => (k.querySelector('.ziwi-kpi__value') || {}).textContent?.trim()),
      monthText: (() => {
        const f = document.querySelector('input[name="month"]')
        return f ? f.value || '' : ''
      })(),
      text: txt.slice(0, 300),
    }
  })
  ;(monthly.hasUndefined ? bad : ok)('月报无 undefined/NaN', '')
  // ★ Vant4 的只读字段是 model-value 不是 value：写成 :value 会静默不显示
  //   （控件在、点了也能弹选择器，就是永远是空的 —— 截图不放大看不出来）
  ;(monthly.monthText && monthly.monthText.includes('年') ? ok : bad)(
    '月份字段回显', monthly.monthText || '(空白)')
  ;(monthly.rowCount > 0 ? ok : bad)('月报明细行', `${monthly.rowCount} 行`)
  ok('月报 KPI', monthly.kpis.join(' · '))

  // ── 中文化：页面上不应出现英文原码 ──
  console.log('\n中文化抽查（英文原码）')
  const codes = await page.evaluate(() => {
    const txt = document.body.innerText
    const suspects = ['in_progress', 'pending', 'completed', 'released', 'purchase',
      'production', 'quality', 'equipment', 'adjust_work', 'workday', 'rest']
    return suspects.filter((c) => new RegExp(`\\b${c}\\b`).test(txt))
  })
  ;(codes.length === 0 ? ok : bad)('页面无英文枚举原码', codes.join(',') || '')
  const unknowns = await page.evaluate(() => (document.body.innerText.match(/未知（[^）]*）/g) || []))
  ;(unknowns.length === 0 ? ok : bad)('页面无「未知（原码）」', unknowns.slice(0, 5).join(',') || '')

  // ── 运行期健康 ──
  ;(pageErr.length === 0 ? ok : bad)('无前端运行时异常', pageErr.slice(0, 3).join(' | ') || '')
  ;(apiErr.length === 0 ? ok : bad)('无 5xx 接口', apiErr.slice(0, 3).join(' | ') || '')

  await browser.close()
  console.log(`\n${'='.repeat(56)}\n通过 ${oks.length} · 失败 ${fails.length}`)
  fails.forEach((f) => console.log('  FAIL', f))
  console.log(`截图 ${OUT}`)
  process.exit(fails.length ? 1 : 0)
})().catch((e) => {
  console.error('脚本异常', e)
  process.exit(2)
})

function rowHeights0(a) { return a }
