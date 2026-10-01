#!/usr/bin/env node
/**
 * AI Copilot（E1）—— 真实服务的 HTTP 烟测（需要后端已启动 + 有效 token）。
 *
 * 与 e2e/copilot_smoke.py（进程内 ASGI，无需服务）互补：
 *   本脚本面向**已部署/本地运行**的 mfg 后端，验证线上契约。
 *
 * 用法：
 *   COPILOT_BASE=http://localhost:8000 COPILOT_TOKEN=<jwt> node e2e/copilot_smoke.js
 *   （可选 COPILOT_TENANT=default）
 *
 * 退出码 0 = 全部通过；非 0 = 存在失败项。
 */
'use strict'

const BASE = process.env.COPILOT_BASE || 'http://localhost:8000'
const TOKEN = process.env.COPILOT_TOKEN || ''
const TENANT = process.env.COPILOT_TENANT || 'default'

const headers = {
  'Content-Type': 'application/json',
  ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
  ...(TENANT ? { 'X-Tenant-Id': TENANT } : {}),
}

const results = []

function check(name, ok, detail) {
  results.push(ok)
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`)
}

async function ask(question) {
  const resp = await fetch(`${BASE}/api/v1/copilot/ask`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ question }),
  })
  const text = await resp.text()
  const events = []
  for (const line of text.split('\n')) {
    const t = line.trim()
    if (t.startsWith('data:')) {
      try {
        events.push(JSON.parse(t.slice(5).trim()))
      } catch {
        /* ignore */
      }
    }
  }
  return events
}

function find(events, type) {
  return events.find((e) => e.type === type)
}

async function main() {
  // ① 真实数值 + 来源脚注
  let ev = await ask('昨天产量是多少')
  let ans = find(ev, 'answer')
  const p1 = ans ? ans.payload : {}
  check(
    '① 昨天产量 → 真实数值 + 来源脚注',
    !!p1.source && !!p1.data,
    `value=${p1.data && p1.data.value} source=${p1.source && p1.source.table_or_caliber}`,
  )

  // ② 写意图被拒
  ev = await ask('帮我创建一个新的工单')
  const rej = find(ev, 'reject')
  check('② 写意图被拒', !!rej && rej.reason === 'write_intent', rej ? rej.reason : 'no reject event')

  // ③ 无数据固定话术
  ev = await ask('上周产量是多少')
  ans = find(ev, 'answer')
  const n3 = ans ? ans.payload.narrative : ''
  check('③ 无数据 → 固定话术（零臆造）', n3.includes('未查询到'), n3.slice(0, 30))

  // ④ 数据源不可用
  ev = await ask('哪台设备本月停机时间最长')
  ans = find(ev, 'answer')
  const p4 = ans ? ans.payload : {}
  check('④ 停机时长 → 暂不可用', p4.answered === false && (p4.narrative || '').includes('暂不可用'))

  const passed = results.filter(Boolean).length
  console.log(`\n=== HTTP 烟测：${passed}/${results.length} 通过 @ ${BASE} ===`)
  process.exit(passed === results.length ? 0 : 1)
}

main().catch((e) => {
  console.error('烟测异常：', e.message)
  process.exit(2)
})
