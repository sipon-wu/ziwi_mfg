<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { get } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { PaginatedResponse } from '@/types'
import type { KpiState } from '@/types/search'
import CockpitKpi from './CockpitKpi.vue'
import ZiwiStateView from '@/components/ziwi/ZiwiStateView.vue'

/**
 * 驾驶舱 · 模块概览
 *
 * 五条约束（都是踩过的坑）：
 * 1. **计数不能靠「拉一页再数」**。原来「未处理安灯」是 `page_size=100` 拉一页后
 *    客户端 filter —— 总量过百后数字被钉在 100 以内，看起来永远"刚好一百条"。
 *    一律用服务端的 `total` / 状态过滤，或专用聚合端点数。
 * 2. **一个模块的接口失败不能拖垮整页**。用 allSettled 隔离，失败项标「未接入」，
 *    其余照常出数。
 * 3. **能碳是独立产品线**（`dna` 实例），本系统只有只读概览 → 卡片上显著标注边界，
 *    否则会被当成"我们自己的功能没做完"。
 * 4. **孤立数字没有信息量**。「在制 6」是大是小？必须给出分母（占比条）或异常语义
 *    （逾期保养 > 0 才染红），否则看板退化成一张数字壁纸。
 * 5. **入口要按权限藏**。没有 M04 权限的人点进"仓储"会直接撞 403 页，
 *    比不给入口更糟。
 */

interface KpiItem {
  label: string
  value: number | string | null
  state: KpiState
  unit?: string
  /** 0..1，有分母才画占比条 */
  ratio?: number | null
  /** 占比条右侧文字，如 "6 / 10" */
  ratioText?: string
  /** 异常语义着色 */
  severity?: 'normal' | 'warn' | 'danger'
  /** 口径说明（悬停可见） */
  hint?: string
}
interface ModuleInfo {
  name: string
  code: string
  /** 进入模块的落点；外部产品线不填 */
  to?: string
  /** 进入前要校验的读权限 */
  perm?: string
  /** 该模块是否为外部产品线（只读概览） */
  external?: boolean
  externalNote?: string
  kpis: KpiItem[]
}

const router = useRouter()
const auth = useAuthStore()

const loading = ref(true)
const updatedAt = ref('')
const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const todayLabel = `${dayjs().format('YYYY-MM-DD')} ${WEEK[dayjs().day()]}`

const blank = (label: string, unit = '', hint?: string): KpiItem =>
  ({ label, value: null, state: 'loading', unit, hint })

const modules = ref<ModuleInfo[]>([
  {
    name: '生产管理', code: 'M01', to: '/work-orders', perm: 'M01:work_order:read',
    // ★ 这里刻意**只放 3 项**：模块卡里各 KPI 行数一致，8 张卡才能等高对齐。
    //   「今日完工」不在这张卡里 —— 它在顶部「今日生产」摘要条里，口径说明也在那儿，
    //   放两处只会让同一个数字有两种读法。
    kpis: [
      blank('工单', '', '工单总数（累计）'),
      blank('在制', '', '已下达 + 生产中 + 已暂停'),
      blank('报工单', '', '报工记录总数（累计）'),
    ],
  },
  {
    // ★ 编号沿用页面既有写法（M02 TPM 设备）。注意代码里设备权限码是
    //   `M06:equipment:*`、而 router 里 M02 指的是 BOM —— 模块编号体系本身
    //   存在两套，统一需要单独拍板，这里不顺手改。
    // ★ 编号必须是 M06。这里原来写 M02 —— 而同一行的权限码是
    //   `M06:equipment:read`，卡上标 M02、实际校验 M06，自相矛盾。
    //   权威编号在 backend/app/constants/modules.py::MODULE_NAMES：
    //   M02=BOM 管理，M06=设备管理 TPM。驾驶舱不做 BOM 卡，所以这里应当是 M06。
    name: 'TPM 设备', code: 'M06', to: '/equipment', perm: 'M06:equipment:read',
    kpis: [
      blank('设备', '', '设备台账总数'),
      blank('待保养', '', '保养任务 status=pending'),
      blank('逾期保养', '', '已过期未完成，> 0 需立即处理'),
    ],
  },
  {
    name: '品质管理', code: 'M03', to: '/quality', perm: 'M03:inspection_order:read',
    kpis: [
      blank('检验单', '', '检验单总数（累计）'),
      blank('未结 NCR', '', 'NCR 待评审 + 评审中，> 0 需闭环'),
      blank('今日报废', '件', '报工报废件数'),
    ],
  },
  {
    name: '基础数据', code: 'M00', to: '/basics/products', perm: 'M00:product:read',
    kpis: [
      blank('产品', '', '产品主数据'),
      blank('物料', '', '物料主数据（含原材料/半成品）'),
      blank('工作中心', '', '车间/工位主数据'),
    ],
  },
  {
    name: '仓储管理', code: 'M04', to: '/wms/stock-query', perm: 'M04:wms_inventory:read',
    kpis: [
      blank('库存预警', '条', '未确认 + 已确认未解决，> 0 需处理'),
      blank('入库单', '', '收货单总数（累计）'),
      blank('出库单', '', '出库单总数（累计）'),
    ],
  },
  {
    name: '安灯系统', code: 'M05', to: '/andon', perm: 'M05:andon_call:read',
    kpis: [
      blank('呼叫', '', '安灯呼叫总数（累计）'),
      blank('未处理', '', '待响应/待处理/已确认/响应中/处理中'),
      blank('已升级', '', '超时升级，> 0 说明响应跟不上'),
    ],
  },
  {
    name: '能碳管理', code: 'M11',
    external: true,
    externalNote: '独立产品线（能碳实例），此处仅只读概览',
    kpis: [
      blank('计量设备', '', '能碳实例的计量设备'),
      blank('碳排放', 't', '首页排放记录合计，非全量'),
      blank('用能告警', '条', '能碳实例的阈值告警'),
    ],
  },
  {
    name: '数据采集', code: 'M12', to: '/data-collection', perm: 'M12:collect_task:read',
    kpis: [
      blank('数据源', '', '已配置数据源'),
      blank('采集记录', '', '采集记录总数'),
      blank('网关', '', '已登记网关'),
    ],
  },
])

function setKpi(code: string, idx: number, patch: Partial<KpiItem>) {
  const m = modules.value.find((x) => x.code === code)
  if (!m || !m.kpis[idx]) {
    // ★ 不许静默。编号写错（比如卡是 M06、取数写 M02）时这里若不吭声，
    //   那几张卡就永远停在 loading，页面只是"看着在转"，没有任何报错。
    console.error(`[cockpit] KPI 定位失败：code=${code} idx=${idx}（模块或 KPI 不存在）`)
    return
  }
  m.kpis[idx] = { ...m.kpis[idx], ...patch }
}

/** 单个 KPI 的统一取数：成功记 real，异常记 unavailable（不冒泡） */
async function feed(
  code: string, idx: number, fn: () => Promise<number | string>,
  opts: { unit?: string } = {},
) {
  try {
    const v = await fn()
    setKpi(code, idx, { value: v, state: 'real', ...opts })
  } catch {
    setKpi(code, idx, { value: null, state: 'unavailable', ...opts })
  }
}

/** 已取到的真实数值；未接入/加载中返回 null（不做 0 处理，0 和"没取到"是两回事） */
function num(code: string, idx: number): number | null {
  const k = modules.value.find((x) => x.code === code)?.kpis[idx]
  if (!k || k.state !== 'real') return null
  const n = typeof k.value === 'number' ? k.value : Number(k.value)
  return Number.isFinite(n) ? n : null
}

/** 画占比条：分母 ≤ 0 或缺任一侧都不画（0/0 没有意义） */
function withRatio(code: string, idx: number, part: number | null, whole: number | null) {
  if (part == null || whole == null || whole <= 0) return
  setKpi(code, idx, { ratio: part / whole, ratioText: `${part} / ${whole}` })
}

/** 异常着色：只有 > 0 才染色，正常态保持安静 */
function withSeverity(code: string, idx: number, n: number | null, level: 'warn' | 'danger') {
  if (n == null || n <= 0) return
  setKpi(code, idx, { severity: level })
}

/** 分页接口只取 total，不拉数据行 */
const total = (path: string, params: Record<string, any> = {}) =>
  get<PaginatedResponse<any>>(path, { page_size: 1, ...params }).then((r) => r.total || 0)

/** 多状态求和：状态过滤是单值参数，只能分次问，但每次都只取 total */
async function totalByStatus(path: string, statuses: string[]) {
  const nums = await Promise.all(
    statuses.map((s) => total(path, { status: s }).catch(() => 0)),
  )
  return nums.reduce((a, b) => a + b, 0)
}

const today = () => dayjs().format('YYYY-MM-DD')

/** 今日摘要（一次性取自日报，M01/M03 的当日指标也复用这份，不重复请求） */
const daily = ref<any>(null)
const dailyState = ref<KpiState>('loading')

const summary = computed(() => {
  if (dailyState.value !== 'real' || !daily.value) return null
  const out = Number(daily.value.total_output ?? 0)
  const scrap = Number(daily.value.total_scrap ?? 0)
  return {
    out,
    wip: Number(daily.value.total_wip_output ?? 0),
    scrap,
    hours: Number(daily.value.total_hours ?? 0),
    /** 报废率分母取完工量；完工为 0 时不给率（0% 会误导成"质量很好"） */
    scrapRate: out > 0 ? Math.round((scrap / out) * 1000) / 10 : null,
  }
})

async function load() {
  loading.value = true
  const t = today()

  // 日报只取一次
  dailyState.value = 'loading'
  daily.value = await get<any>('/reports/daily', { report_date: t }).catch(() => null)
  dailyState.value = daily.value ? 'real' : 'unavailable'

  const fromDaily = (key: string) => () => {
    if (!daily.value) return Promise.reject(new Error('日报不可用'))
    return Promise.resolve(Number(daily.value[key] ?? 0))
  }

  // ── M01 生产管理 ──
  await feed('M01', 0, () => total('/work-orders'))
  await feed('M01', 1, () =>
    // 在制 = 已下达 + 生产中 + 已暂停（草稿还没投产，不算在制）
    totalByStatus('/work-orders', ['released', 'in_progress', 'paused']))
  await feed('M01', 2, () => total('/work-reports'))
  withRatio('M01', 1, num('M01', 1), num('M01', 0))

  // ── M06 TPM ──
  // ★ 这里的编号必须和上面模块卡的 `code` 逐字一致。`setKpi` 靠 code 找卡，
  //   找不到时**什么都不做**（不抛错）→ 那 3 张卡永远停在 state='loading'，
  //   `<van-loading>` 一直转，页面看起来只是在"慢慢加载"，实际是死等。
  await feed('M06', 0, () => total('/equipment'))
  await feed('M06', 1, () => totalByStatus('/maintenance-tasks', ['pending']))
  await feed('M06', 2, async () => {
    const list = await get<any[]>('/maintenance-tasks/overdue')
    return Array.isArray(list) ? list.length : 0
  })
  withRatio('M06', 2, num('M06', 2), num('M06', 1))
  withSeverity('M06', 2, num('M06', 2), 'danger')

  // ── M03 品质 ──
  await feed('M03', 0, () => total('/inspection-orders'))
  await feed('M03', 1, () => totalByStatus('/ncr', ['open', 'reviewing']))
  await feed('M03', 2, fromDaily('total_scrap'), { unit: '件' })
  withSeverity('M03', 1, num('M03', 1), 'warn')

  // ── M00 基础数据 ──
  await feed('M00', 0, () => total('/products'))
  // ★ 物料挂在 `/wms` 前缀下（`app/api/wms.py` 的 APIRouter prefix），
  //   不是 `/materials` —— 少一段前缀就是干净 404，KPI 静静变成「未接入」。
  await feed('M00', 1, () => total('/wms/materials'))
  await feed('M00', 2, () => total('/work-centers'))

  // ── M04 仓储（端点全在 /wms 前缀下）──
  await feed('M04', 0, () =>
    // 未闭环预警 = open（未确认）+ acknowledged（已确认未解决）
    totalByStatus('/wms/inventory-alerts', ['open', 'acknowledged']))
  await feed('M04', 1, () => total('/wms/receipt-orders'))
  await feed('M04', 2, () => total('/wms/issue-orders'))
  withSeverity('M04', 0, num('M04', 0), 'warn')

  // ── M05 安灯 ──
  await feed('M05', 0, () => total('/andon/calls'))
  await feed('M05', 1, () =>
    // 未处理 = 待响应/待处理/已确认/响应中/处理中
    // ★ 这里**不含 escalated**：已升级单独一项，两项互斥才不会把同一张单数两遍
    totalByStatus('/andon/calls',
      ['pending', 'open', 'acknowledged', 'responding', 'in_progress']))
  await feed('M05', 2, () => totalByStatus('/andon/calls', ['escalated']))
  withRatio('M05', 1, num('M05', 1), num('M05', 0))
  withSeverity('M05', 1, num('M05', 1), 'warn')
  withSeverity('M05', 2, num('M05', 2), 'danger')

  // ── M11 能碳（外部产品线，失败即未接入，不重试）──
  await feed('M11', 0, () => total('/energy/devices'))
  await feed('M11', 1, async () => {
    const r = await get<PaginatedResponse<any>>('/energy/carbon/emissions', { page_size: 100 })
    const items: any[] = r.items || []
    const sum = items.reduce((s, i) => s + Number(i.emission_amount || 0), 0)
    return Math.round(sum * 100) / 100
  }, { unit: 't' })
  await feed('M11', 2, () => total('/energy/alerts'))

  // ── M12 数据采集 ──
  await feed('M12', 0, () => total('/collect/data-sources'))
  await feed('M12', 1, () => total('/collect/records'))
  await feed('M12', 2, () => total('/collect/gateways'))

  updatedAt.value = dayjs().format('HH:mm:ss')
  loading.value = false
}

/** 有任何一个真实值就算"有数据"，避免个别模块未接入时整页变成空态 */
const hasData = computed(() =>
  modules.value.some((m) => m.kpis.some((k) => k.state === 'real')),
)
const realCount = computed(() =>
  modules.value.reduce((n, m) => n + m.kpis.filter((k) => k.state === 'real').length, 0),
)
const kpiCount = computed(() =>
  modules.value.reduce((n, m) => n + m.kpis.length, 0),
)
/** 口径覆盖度：真实接入的 KPI / 全部 KPI。比"能不能打开"更能说明看板是否完整 */
const coverage = computed(() =>
  kpiCount.value ? Math.round((realCount.value / kpiCount.value) * 100) : 0,
)

/**
 * 卡片内列数：4 项排 2×2（排 3 列会落单一行只有 1 张，更难看），
 * 其余按项数铺满、最多 3 列。
 */
const colsOf = (m: ModuleInfo) => (m.kpis.length === 4 ? 2 : Math.min(m.kpis.length, 3))

/** 没权限不给入口：点进去撞 403 比不给更糟 */
const canEnter = (m: ModuleInfo) =>
  !!m.to && (auth.hasPerm(m.perm || '') || !auth.hasPermissionsLoaded)

function enter(m: ModuleInfo) {
  if (canEnter(m) && m.to) router.push(m.to)
}

onMounted(load)
</script>

<template>
  <div class="cockpit">
    <div class="cockpit__head">
      <div>
        <h2 class="cockpit__title">驾驶舱 · 模块概览</h2>
        <div class="cockpit__sub">
          <span>{{ todayLabel }}</span>
          <span class="cockpit__dot">·</span>
          <span>KPI 接入 {{ realCount }}/{{ kpiCount }}（{{ coverage }}%）</span>
          <span v-if="updatedAt" class="cockpit__dot">·</span>
          <span v-if="updatedAt">数据时点 {{ updatedAt }}</span>
        </div>
      </div>
      <van-button size="small" plain type="primary" :loading="loading" @click="load">刷新</van-button>
    </div>

    <!-- 今日摘要：当日几个"经营级"数字，避免在模块卡里东找西找。
         ★ 必须是**块**，不能是线分隔的文字带 —— 顶部一条 5 段的竖线，扫过去
         就是"一堆点线"，和下面 24 块 KPI 完全不成一片。这里直接复用
         CockpitKpi，顶部与模块区共用同一套块样式：改一处两边一起变，
         也免得又长出一套"看起来差不多但数值字号差 2px"的第二视觉。 -->
    <section class="today">
      <header class="today__head">
        <span class="today__title">今日生产</span>
        <span class="today__hint">完工口径 · 只认末道工序</span>
        <button type="button" class="today__more" @click="router.push('/reports')">
          生产报表<van-icon name="arrow" />
        </button>
      </header>
      <div class="today__blocks">
        <CockpitKpi
          label="完工产出"
          :value="summary ? summary.out : '—'"
          :unit="summary ? '件' : ''"
          :state="dailyState"
          hint="只统计路线末道工序的完工量，不是各工序产量相加"
        />
        <CockpitKpi
          label="工序流转"
          :value="summary ? summary.wip : '—'"
          :unit="summary ? '件' : ''"
          :state="dailyState"
          hint="全部工序的报工量累计，含在制；与完工产出不同口径，不可相加"
        />
        <CockpitKpi
          label="报废"
          :value="summary ? summary.scrap : '—'"
          :unit="summary ? '件' : ''"
          :state="dailyState"
          :severity="summary && summary.scrap > 0 ? 'danger' : 'normal'"
          hint="报工时报废的件数（投入侧已计入报废量）"
        />
        <CockpitKpi
          label="报废率"
          :value="summary && summary.scrapRate !== null ? summary.scrapRate : '—'"
          :unit="summary && summary.scrapRate !== null ? '%' : ''"
          :state="dailyState"
          :severity="summary && summary.scrapRate !== null && summary.scrapRate > 0 ? 'danger' : 'normal'"
          hint="报废 ÷ 完工产出。完工为 0 时不给率 —— 0% 会被读成质量很好"
        />
        <CockpitKpi
          label="人工工时"
          :value="summary ? summary.hours : '—'"
          :unit="summary ? 'h' : ''"
          :state="dailyState"
          hint="运行时间 + 换型时间，按人计；与设备机时不是同一个口径"
        />
      </div>
    </section>

    <ZiwiStateView
      v-if="!loading && !hasData"
      state="empty-true"
      object-name="业务数据"
      hint="请先创建工单和报工"
      @retry="load"
    />

    <div class="cockpit__grid">
      <section v-for="mod in modules" :key="mod.code" class="mod">
        <header
          class="mod__head"
          :class="{ 'mod__head--link': canEnter(mod) }"
          @click="enter(mod)"
        >
          <span class="mod__code">{{ mod.code }}</span>
          <span class="mod__name">{{ mod.name }}</span>
          <van-tag v-if="mod.external" type="warning" plain size="medium">外部</van-tag>
          <span v-if="canEnter(mod)" class="mod__enter">
            进入<van-icon name="arrow" />
          </span>
        </header>
        <p v-if="mod.externalNote" class="mod__note">{{ mod.externalNote }}</p>
        <div
          class="mod__kpis"
          :style="{ gridTemplateColumns: `repeat(${colsOf(mod)}, minmax(0, 1fr))` }"
        >
          <CockpitKpi v-for="(kpi, i) in mod.kpis" :key="i" v-bind="kpi" />
        </div>
      </section>
    </div>

    <footer class="cockpit__foot">
      <p>
        计数口径：<b>工单 / 报工 / 检验单 / 各类单据</b>为累计总量；
        <b>今日完工 / 今日报废</b>取当日生产日报。完工只认工艺路线末道工序，
        与「工序流转」不是同一口径，不可相加。
      </p>
      <p>
        M11 能碳为独立产品线（能碳实例），本系统内仅只读概览，不参与本页交互。
      </p>
    </footer>
  </div>
</template>

<style scoped>
.cockpit { padding: var(--ziwi-gap-lg); }

.cockpit__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ziwi-gap-md);
  margin-bottom: var(--ziwi-gap-md);
}
.cockpit__title {
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  color: var(--ziwi-text-primary);
}
.cockpit__sub {
  margin-top: var(--ziwi-gap-xs);
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ziwi-gap-xs);
}
.cockpit__dot { color: var(--ziwi-text-placeholder); }

/* ── 今日摘要（块状）──
   旧写法是「一段文字标题 + 5 个左边框竖线分隔的数字」，整条又扁又长，
   和下面 24 块 KPI 是两种语言：上面是线、下面是块，页面被切成两截。
   现在把它也变成一张"卡 + 块"：卡头和模块卡同规格（48 触控高 + 标题 +
   右侧入口），5 个数字各占一块，块样式直接来自 CockpitKpi（浅色实心底、
   块内居中、无描边），于是从页面顶部到底部只有一种块面语言。 */
.today {
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border-card);
  border-radius: var(--ziwi-radius-card);
  box-shadow: var(--ziwi-shadow-card);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md) var(--ziwi-gap-md);
  margin-bottom: var(--ziwi-gap-md);
}
.today__head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-touch-min, 48px);
  margin-bottom: var(--ziwi-gap-sm);
}
.today__title {
  font-size: var(--ziwi-font-size-lg);
  font-weight: 600;
  color: var(--ziwi-text-primary);
}
.today__hint {
  font-size: var(--ziwi-font-size-xs);
  color: var(--ziwi-text-muted);
}
.today__blocks {
  display: grid;
  /* ★ 5 块固定等分。`minmax(0, 1fr)` 的下限必须显式写 0 —— 默认下限是
     min-content，"工序流转""人工工时"这类标签加上数字会把列撑宽，
     5 块就变成宽窄不一的色块，矩阵又塌了。 */
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--ziwi-gap-sm);
}
@media (max-width: 900px) {
  .today__blocks { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.today__more {
  margin-left: auto;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: var(--ziwi-gap-xs);
  min-height: var(--ziwi-touch-min, 48px);
  padding: 0 var(--ziwi-gap-md);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-md);
  background: transparent;
  color: var(--ziwi-primary);
  font-size: var(--ziwi-font-size-md);
  cursor: pointer;
}
.today__more:hover { background: var(--ziwi-primary-bg); }

/* ── 模块卡网格 ──
   ★ 两种"看起来空"要分开治：
   1. 旧写法 van-row/van-col 是**等高拉伸**：M11 只有 2 个 KPI，却被旁边的 M01
      撑到同样高度，下半张卡整片留白 —— 空在卡片里面。
   2. 只把 align-items 改成 start 又会出现新问题：同一行里短卡（M02）下方留出
      一百多像素页面底色 —— 空在卡片外面。
   最终取「行内等高 + 卡片竖向 flex」：卡等高，但 KPI 网格用 `flex:1` 吃掉余量，
   空的地方落在 KPI 卡内部（有边框有节奏），页面不会出现裸露的空洞。
   列宽 minmax(400px) 保证 1366 及以上是 2 列，窄屏自动收成 1 列。 */
.cockpit__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  align-items: stretch;
  gap: var(--ziwi-gap-md);
}

.mod {
  display: flex;
  flex-direction: column;
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border-card);
  border-radius: var(--ziwi-radius-card);
  box-shadow: var(--ziwi-shadow-card);
  /* 内边距收紧一档：KPI 已经是带底色的块，再留 20px 白边就成了
     "白框里套色块"的三层嵌套，块面反而不成片 */
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md) var(--ziwi-gap-md);
}

.mod__head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-touch-min, 48px);
  margin-bottom: var(--ziwi-gap-sm);
}
.mod__head--link { cursor: pointer; }
.mod__head--link:hover .mod__enter { color: var(--ziwi-primary); }
.mod__code {
  font-size: var(--ziwi-font-size-xs);
  font-weight: 600;
  color: var(--ziwi-primary);
  background: var(--ziwi-primary-bg);
  border-radius: var(--ziwi-radius-sm);
  padding: 2px 6px;
  flex: 0 0 auto;
}
.mod__name {
  font-size: var(--ziwi-font-size-lg);
  font-weight: 600;
  color: var(--ziwi-text-primary);
}
.mod__enter {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--ziwi-gap-2xs);
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
  flex: 0 0 auto;
}
.mod__note {
  margin: calc(-1 * var(--ziwi-gap-2xs)) 0 var(--ziwi-gap-sm);
  font-size: var(--ziwi-font-size-xs);
  color: var(--ziwi-text-muted);
}

.mod__kpis {
  display: grid;
  /* 吃掉卡片剩余高度：卡片被同行拉高时，空留在 KPI 卡内部而不是页面底色 */
  flex: 1 1 auto;
  grid-auto-rows: minmax(0, 1fr);
  gap: var(--ziwi-gap-sm);
}

.cockpit__foot {
  margin-top: var(--ziwi-gap-lg);
  padding-top: var(--ziwi-gap-md);
  border-top: 1px solid var(--ziwi-border-light);
  font-size: var(--ziwi-font-size-xs);
  color: var(--ziwi-text-muted);
  line-height: var(--ziwi-lineheight-normal);
}
.cockpit__foot p { margin: 0 0 var(--ziwi-gap-2xs); }
.cockpit__foot b { color: var(--ziwi-text-secondary); font-weight: 500; }

@media (max-width: 720px) {
  .cockpit__grid { grid-template-columns: 1fr; }
  .today__items { gap: var(--ziwi-gap-lg); }
}
</style>
