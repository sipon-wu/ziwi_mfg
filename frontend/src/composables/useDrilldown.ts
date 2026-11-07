/**
 * 驾驶舱 KPI 下探的运行时契约。
 *
 * 为什么需要这个东西
 * ------------------
 * 驾驶舱的每个 KPI 都是「问后端 total 得到的数」。原来 KPI 卡不可点，用户看到
 * 「在制 6」没法回答「是哪 6 张单」—— 数字没有下探出口。而只加一个
 * `router.push('/work-orders')` 更糟：落到**全量列表**，数字与列表对不上，
 * 看起来像下探了，其实是换个页面。
 *
 * 多状态 KPI 的坑
 * ---------------
 * 「在制」= released + in_progress + paused 三个状态之和，但后端列表端点的
 * `status` 是**单值**参数。只下探 `status=in_progress` 会静默少掉另外两类单，
 * 数字仍然对不上。所以 query 用逗号多值，由本模块**按状态并发取数再合并去重**，
 * 与驾驶舱 `totalByStatus()` 的取数集合来自同一份常量，不能各写各的。
 *
 * 两个"看起来对、其实没生效"的坑（2026-11-08 修）
 * ---------------------------------------------
 * 1. `truncated` 原来写成 `computed(() => false)` —— 永远 false，截断提示
 *    永远不显示，界面全绿但一个状态都没量过。现在由 `loadMerged()` 实际回写
 *    `hitLimit`，静态闸会拦「永假的 truncated」。
 * 2. `clear()` 只做 router.replace，组件**不会重新挂载**，`onMounted` 不再跑，
 *    于是清除过滤后列表仍是上一次的下探结果。所以必须提供 `onChange()`，
 *    由列表页注册「query 变了就重新取数」。
 *
 * 用法（列表页）：
 *
 *     const drill = useDrilldown()
 *     async function loadData() {
 *       if (drill.active.value) {
 *         const { items, total } = await drill.loadMerged<T>('/work-orders')
 *         rows.value = items; total.value = total
 *       } else { /* 原有分页逻辑 *\/ }
 *     }
 *     drill.onChange(() => { resetPage(); void loadData() })
 *
 * 模板里放 `<DrilldownBanner :total="total" />` 显示来源、总量与清除入口，
 * 避免用户被一个看不见的过滤困住。
 *
 * ⚠️ 下探视图是「构成这个数字的那些单据」，每状态最多 100 条、不分页；
 *    超出时由 `truncated` 在界面上提示。常规浏览仍走原来的分页取数。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'

/** 单状态取数上限。下探是「看构成」，不是 browse 全量列表。 */
export const DRILL_PAGE_SIZE = 100

export function useDrilldown() {
  const route = useRoute()
  const router = useRouter()

  const statuses = computed(() =>
    String(route.query.status ?? '').split(',').map((s) => s.trim()).filter(Boolean))
  const overdue = computed(() => String(route.query.overdue ?? '') === '1')
  const active = computed(() => statuses.value.length > 0 || overdue.value)
  const label = computed(() => {
    if (overdue.value) return '驾驶舱下探 · 逾期保养'
    if (statuses.value.length) return `驾驶舱下探 · ${statuses.value.length} 个状态`
    return ''
  })

  /** 由 loadMerged 实际回写：某个状态恰好拉满一页，说明后面可能还有 */
  const hitLimit = ref(false)
  const truncated = computed(() => hitLimit.value)

  /** 清掉下探条件并回到常规分页视图（replace，不往历史里塞一页） */
  function clear() {
    const q = { ...route.query }
    delete q.status
    delete q.overdue
    hitLimit.value = false
    void router.replace({ path: route.path, query: q })
  }

  /**
   * 下探条件变化（清除 / 从另一个 KPI 下探进来）时重新取数。
   * 字符串按值比较，只有 query 真变了才触发，不会每帧空转。
   */
  function onChange(cb: () => void) {
    watch(
      () => `${String(route.query.status ?? '')}|${String(route.query.overdue ?? '')}`,
      () => { hitLimit.value = false; cb() },
    )
  }

  /**
   * 按多状态并发取数并合并去重，返回 `{ items, total, hitLimit }`。
   * 单状态失败只影响那一个状态，不能让整页崩成 500 —— 与驾驶舱
   * `totalByStatus` 的 `.catch(() => 0)` 同一套降级。
   */
  async function loadMerged<T>(path: string, extra: Record<string, any> = {}) {
    const list = statuses.value.length ? statuses.value : ['']
    const empty = { items: [] as T[], total: 0 } as unknown as PaginatedResponse<T>
    const res = await Promise.all(list.map((s) =>
      get<PaginatedResponse<T>>(path, {
        page: 1, page_size: DRILL_PAGE_SIZE,
        ...(s ? { status: s } : {}),
        ...extra,
      }).catch(() => empty)))
    const seen = new Set<unknown>()
    const items: T[] = []
    let total = 0
    let limit = false
    for (const r of res) {
      total += Number(r.total || 0)
      const part = (r.items || []) as any[]
      if (part.length >= DRILL_PAGE_SIZE) limit = true
      for (const it of part) {
        const key = it && typeof it === 'object' && 'id' in it ? it.id : Symbol()
        if (seen.has(key)) continue
        seen.add(key)
        items.push(it as T)
      }
    }
    hitLimit.value = limit
    return { items, total, hitLimit: limit }
  }

  /** 逾期保养走专门的 `/maintenance-tasks/overdue` 端点（不是 status 过滤） */
  async function loadOverdue<T>(path: string) {
    const list = await get<T[]>(path).catch(() => [] as T[])
    const arr = Array.isArray(list) ? list : []
    hitLimit.value = false
    return { items: arr, total: arr.length, hitLimit: false }
  }

  return {
    statuses, overdue, active, label, truncated,
    clear, onChange, loadMerged, loadOverdue,
  }
}
