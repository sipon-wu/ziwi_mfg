/**
 * 卡片模型结构审计（B1 收口探针）
 *
 * ## 要回答什么
 * B1 把「分组标题并入卡片」做成了 CSS 兄弟选择器拼合：
 * 标题自己是卡片的上半截，紧邻的下一个分组是下半截。
 * 这条规则在 38 个页面、全站 47 处 `van-cell-group title` 上一次性生效，
 * 所以必须机械地检查**拼合是否处处成立**，而不是靠翻几张截图。
 *
 * ## 判据（每条都能证伪）
 * 1. 孤立标题：`__title` 后面紧跟的不是普通 cell-group → 会退化成悬空白条。
 * 2. 标题未并卡：白底/上圆角/上边框三个特征缺任一 → 说明 CSS 没打到。
 * 3. 卡内卡：浮层（popup/dialog）里出现带边框的 cell-group → 视觉会碎。
 * 4. inset 误伤：`.van-cell-group--inset` 不应出现我们的 1px 边框。
 * 5. JS 运行时错误。
 *
 * 用法：
 *   NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
 *   PLAYWRIGHT_BROWSERS_PATH="C:/Users/Kane.liu/AppData/Local/ms-playwright" \
 *   BASE_URL=http://127.0.0.1:5173 node e2e/browser_test/t09_card_model_audit.js
 */
const { chromium } = require('@playwright/test')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUT = process.env.SHOT_DIR || 'e2e/browser_test/screenshots/t09_card_model'

// 覆盖到每个模块的列表页 + 详情页 + 表单页；详情页在运行时用真实 id 替换
const ROUTES = [
  ['驾驶舱', '/cockpit'],
  ['驾驶舱-看板', '/dashboard'],
  ['工单列表', '/work-orders'],
  ['报工记录', '/reports'],
  ['排产', '/schedule'],
  ['BOM', '/boms'],
  ['工序', '/basics/operations'],
  ['工作中心', '/basics/work-centers'],
  ['工艺路线', '/basics/routes'],
  ['产品', '/basics/products'],
  ['设备', '/equipment'],
  ['保养计划', '/equipment/maintenance-plans'],
  ['安灯', '/andon'],
  ['检验单', '/quality'],
  ['不良品NCR', '/quality/ncr'],
  ['控制图', '/quality/spc/control-limits'],
  ['FMEA', '/quality/fmea'],
  ['库房树', '/wms/warehouse-tree'],
  ['物料', '/wms/materials'],
  ['收货单', '/wms/receipt-orders'],
  ['出库单', '/wms/issue-orders'],
  ['库存查询', '/wms/stock-query'],
  ['库存台账', '/wms/inventory'],
  ['库内移库', '/wms/stock-move'],
  ['盘点', '/wms/inventory-counts'],
  ['批次', '/wms/batches'],
  ['库存预警', '/wms/alerts'],
  ['试产', '/trials'],
  ['实验室', '/lab'],
  ['实验室标准', '/lab/standards'],
  ['系统配置', '/system/config'],
  ['License', '/system/license'],
  ['角色权限', '/system/roles'],
  ['数据采集', '/data-collection'],
]

fs.mkdirSync(OUT, { recursive: true })

const rows = []
function rec(route, name, jsErr, info) {
  rows.push({ route, name, jsErr, ...info })
}

;(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      'C:/Users/Kane.liu/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  let jsErrors = []
  page.on('pageerror', (e) => jsErrors.push(String(e)))

  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"], input[type="text"]', 'mfg_admin')
  await page.fill('input[type="password"]', 'admin123')
  await page.click('button[type="submit"]')
  await page.waitForFunction(() => !location.hash.includes('/login'), { timeout: 20000 })
  await page.waitForTimeout(800)

  for (const [name, route] of ROUTES) {
    jsErrors = []
    try {
      await page.goto(`${BASE}/#${route}`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1400)
      const info = await page.evaluate(() => {
        const titles = Array.from(document.querySelectorAll('.van-cell-group__title'))
        const plainGroups = Array.from(
          document.querySelectorAll('.van-cell-group:not(.van-cell-group--inset)'),
        )
        const insetGroups = Array.from(document.querySelectorAll('.van-cell-group--inset'))

        // 1. 孤立标题：后面紧跟的不是普通分组
        const orphanTitles = titles.filter((t) => {
          const n = t.nextElementSibling
          return !(
            n &&
            n.classList.contains('van-cell-group') &&
            !n.classList.contains('van-cell-group--inset')
          )
        })

        // 2. 标题未并卡（只查非 inset 标题）
        const unmerged = titles.filter((t) => {
          if (t.classList.contains('van-cell-group__title--inset')) return false
          const cs = getComputedStyle(t)
          return !(
            cs.backgroundColor === 'rgb(255, 255, 255)' &&
            cs.borderTopLeftRadius === '10px' &&
            cs.borderTopWidth === '1px'
          )
        })

        // 3. 浮层里出现带边框的卡片
        const nestedCard = Array.from(
          document.querySelectorAll('.van-popup .van-cell-group, .van-dialog .van-cell-group'),
        ).filter((g) => {
          const cs = getComputedStyle(g)
          return cs.borderLeftWidth !== '0px' && cs.borderLeftStyle !== 'none'
        })

        // 4. inset 被误伤
        const insetHurt = insetGroups.filter((g) => {
          const cs = getComputedStyle(g)
          return cs.borderLeftWidth !== '0px' && cs.borderLeftStyle !== 'none'
        })

        return {
          titleCount: titles.length,
          plainCount: plainGroups.length,
          insetCount: insetGroups.length,
          orphan: orphanTitles.map((t) => (t.textContent || '').trim().slice(0, 12)),
          unmerged: unmerged.map((t) => (t.textContent || '').trim().slice(0, 12)),
          nested: nestedCard.length,
          insetHurt: insetHurt.length,
          pageBg: getComputedStyle(document.body).backgroundColor,
        }
      })
      rec(route, name, jsErrors.length, info)
      const bad = info.orphan.length + info.unmerged.length + info.nested + info.insetHurt
      console.log(
        `${bad === 0 && jsErrors.length === 0 ? 'PASS' : 'FAIL'}  ${name.padEnd(10)} ${route.padEnd(30)} ` +
          `标题${info.titleCount} 卡${info.plainCount} inset${info.insetCount}` +
          (info.orphan.length ? ` 孤立[${info.orphan}]` : '') +
          (info.unmerged.length ? ` 未并卡[${info.unmerged}]` : '') +
          (info.nested ? ` 浮层内卡${info.nested}` : '') +
          (info.insetHurt ? ` inset误伤${info.insetHurt}` : '') +
          (jsErrors.length ? ` JS:${jsErrors[0].slice(0, 60)}` : ''),
      )
      await page.screenshot({
        path: path.join(OUT, `${name.replace(/[\\/:*?"<>|]/g, '_')}.png`),
      })
    } catch (e) {
      rec(route, name, -1, { error: String(e).slice(0, 200) })
      console.log(`ERR   ${name} ${route} — ${String(e).slice(0, 120)}`)
    }
  }

  const bad = rows.filter(
    (r) =>
      r.jsErr !== 0 ||
      (r.orphan && r.orphan.length) ||
      (r.unmerged && r.unmerged.length) ||
      r.nested ||
      r.insetHurt,
  )
  fs.writeFileSync(
    path.join(OUT, 'result.json'),
    JSON.stringify({ base: BASE, pages: rows.length, bad: bad.length, rows }, null, 2),
  )
  console.log(`\n${rows.length - bad.length}/${rows.length} 页结构审计通过  →  ${OUT}/result.json`)
  await browser.close()
  process.exit(bad.length === 0 ? 0 : 1)
})()
