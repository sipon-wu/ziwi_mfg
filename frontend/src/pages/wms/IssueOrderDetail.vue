<script setup lang="ts">
/**
 * 出库单详情（T04 子步骤 1：先把 404 堵掉）
 *
 * ## 背景
 * `IssueOrderList.vue:86` 早就把每一行 link 到 `/wms/issue-orders/{id}`，
 * 但 `router/index.ts` 里只有列表路由 —— 现场一点就落 NotFound 兜底页。
 * 这不是"少建一个页面"，是**列表给出的承诺兑现不了**：UE §2.3 的
 * 「列表行展开（只读明细）→ 无执行入口」正是这么来的。
 *
 * ## 为什么行明细复用 scan 端点
 * 后端没有 `GET /issue-orders/{id}/items`（只有 `scan` 与 `get`）。
 * `scan?code={issue_no}` 返回的正是"单头 + 逐行 remain_qty + 拣货建议"，
 * 且与执行页用的是**同一份数据形状** —— 详情页与执行页不会出现
 * "详情说欠 8 个、执行页说欠 5 个"这种口径分裂。
 * 只读页拿 `issued_no` 去 scan 是纯读操作，不产生任何副作用。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api/client'
import { formatQty, txt } from '@/config/uiText'
import { TERM } from '@/config/term'
import { getStateEntry } from '@/config/statusDict'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiActionBar from '@/components/ziwi/ZiwiActionBar.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'

interface IssueOrder {
  id: number
  issue_no: string
  issue_type: string
  status: string
  warehouse_id: number
  warehouse_name: string
  total_qty: number
  issued_qty: number
  recipient: string | null
  source_doc_no: string | null
  created_at: string
  short_closed?: boolean
  shortage_reason?: string | null
}

interface IssueLine {
  item_id: number
  line_no: number
  material_id: number
  material_code: string
  material_name: string
  required_qty: number
  issued_qty: number
  remain_qty: number
  unit: string | null
  batch_no: string | null
  pick_status: string | null
  suggest_batch_no: string | null
  suggest_location_name: string | null
}

interface ScanPayload {
  order: IssueOrder
  matched_by: string
  can_execute: boolean
  blocked_reason: string | null
  lines: IssueLine[]
  summary: { line_count: number; done_lines: number; diff_lines: number }
}

const route = useRoute()
const router = useRouter()

const ISSUE_TYPE_MAP: Record<string, string> = {
  production: '生产出库',
  sales: '销售出库',
  scrap: '报废出库',
  transfer: '调拨出库',
}

const orderId = computed(() => Number(route.params.id))
const order = ref<IssueOrder | null>(null)
const payload = ref<ScanPayload | null>(null)
const loading = ref(true)
const loadFailed = ref(false)
const loadErrorKind = ref<'network' | 'business'>('network')
const loadErrorMessage = ref('')

const state = computed<StateKind>(() => {
  if (loading.value) return 'loading'
  if (loadFailed.value) return 'failed'
  if (!order.value) return 'empty-true'
  return 'ready'
})

const statusEntry = computed(() => getStateEntry('wms_issue', order.value?.status ?? ''))

const canExecute = computed(() => payload.value?.can_execute ?? false)
const blockedReason = computed(() => payload.value?.blocked_reason || '')

const lines = computed<IssueLine[]>(() => {
  const all = payload.value?.lines ?? []
  // 未发完的行优先：现场打开详情就是为了看"还差哪几行"
  return [...all].sort((a, b) => {
    const aDone = a.remain_qty <= 0 ? 1 : 0
    const bDone = b.remain_qty <= 0 ? 1 : 0
    if (aDone !== bDone) return aDone - bDone
    return a.line_no - b.line_no
  })
})

const shortageLines = computed(() => lines.value.filter((l) => l.remain_qty > 0))

async function load(): Promise<void> {
  loading.value = true
  loadFailed.value = false
  try {
    const o = await get<IssueOrder>(`/wms/issue-orders/${orderId.value}`)
    order.value = o
    // 行明细复用 scan（按单号精确定位，与执行页同一份数据形状）
    payload.value = await get<ScanPayload>('/wms/issue-orders/scan', { code: o.issue_no })
  } catch (error) {
    loadFailed.value = true
    const hasResponse = Boolean((error as { response?: unknown })?.response)
    loadErrorKind.value = hasResponse ? 'business' : 'network'
    const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
      ?.data?.detail
    // scan 失败（例如历史单据无行）不该让整页空白：单头已经拿到了
    loadErrorMessage.value = detail?.message || txt.empty.failed()
  } finally {
    loading.value = false
  }
}

function goExecute(): void {
  router.push(`/wms/issue-orders/${orderId.value}/execute`)
}

/**
 * 发料执行页是否已注册。
 *
 * 本轮只交付"堵 404"的只读详情；执行页与它的路由**同批**提交。
 * 路由没注册时不渲染「开始出库」——列表/详情给出的入口必须是能兑现的承诺，
 * 否则就是把 404 从列表挪到详情（同一个坑换个位置）。
 */
const hasExecuteRoute = computed<boolean>(() => router.hasRoute('IssueOrderExecute'))

onMounted(load)
</script>

<template>
  <div class="iod-page">
    <header class="iod-head">
      <button type="button" class="iod-head__back" aria-label="返回" @click="router.push('/wms/issue-orders')">
        ‹
      </button>
      <div class="iod-head__main">
        <h1 class="iod-head__title">出库单详情</h1>
        <ZiwiCodeText
          v-if="order"
          class="iod-head__no"
          :code="order.issue_no"
          label="出库单号"
        />
      </div>
      <span class="ziwi-state" :class="`ziwi-state--${statusEntry.semantic}`">
        <van-icon :name="statusEntry.icon" />
        {{ statusEntry.label }}
      </span>
    </header>

    <ZiwiStateView
      :state="state"
      skeleton="detail"
      :object-name="'出库单'"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="40vh"
      @retry="load"
    >
      <section v-if="order" class="iod-card">
        <dl class="iod-grid">
          <div class="iod-grid__row">
            <dt>出库类型</dt>
            <dd>{{ ISSUE_TYPE_MAP[order.issue_type] || order.issue_type || '-' }}</dd>
          </div>
          <div class="iod-grid__row">
            <dt>{{ TERM.warehouse }}</dt>
            <dd>{{ order.warehouse_name || '-' }}</dd>
          </div>
          <div class="iod-grid__row">
            <dt>领料人</dt>
            <dd>{{ order.recipient || '-' }}</dd>
          </div>
          <div class="iod-grid__row">
            <dt>来源单号</dt>
            <dd>{{ order.source_doc_no || '-' }}</dd>
          </div>
          <div class="iod-grid__row">
            <dt>需求 / 已发</dt>
            <dd>
              {{ formatQty(order.total_qty) }} / {{ formatQty(order.issued_qty) }}
            </dd>
          </div>
          <div class="iod-grid__row">
            <dt>创建时间</dt>
            <dd>{{ String(order.created_at || '').replace('T', ' ').slice(0, 16) || '-' }}</dd>
          </div>
        </dl>

        <p v-if="order.short_closed" class="iod-note iod-note--warn">
          本单为差额结案，原因：{{ order.shortage_reason || '未填写' }}
        </p>
        <p v-else-if="blockedReason" class="iod-note">{{ blockedReason }}</p>
      </section>

      <section v-if="order" class="iod-card">
        <div class="iod-card__bar">
          <h2 class="iod-card__title">明细（{{ lines.length }} 行）</h2>
          <span v-if="shortageLines.length" class="iod-card__pending">
            {{ shortageLines.length }} 行未发完
          </span>
        </div>

        <!-- 行明细为空是"真无数据"，不是加载失败 -->
        <p v-if="lines.length === 0" class="iod-empty">
          {{ txt.empty.true('出库明细', '在出库单里添加物料') }}
        </p>

        <ul v-else class="iod-lines">
          <li v-for="line in lines" :key="line.item_id" class="iod-line">
            <div class="iod-line__main">
              <span class="iod-line__no">{{ line.line_no }}</span>
              <span class="iod-line__name">{{ line.material_name || line.material_code }}</span>
              <span
                class="iod-line__tag"
                :class="line.remain_qty <= 0 ? 'iod-line__tag--done' : 'iod-line__tag--pending'"
              >
                {{ line.remain_qty <= 0 ? txt.execute.lineDone() : txt.execute.linePending() }}
              </span>
            </div>
            <div class="iod-line__nums">
              <span>需求 {{ formatQty(line.required_qty) }}{{ line.unit || '' }}</span>
              <span>已发 {{ formatQty(line.issued_qty) }}{{ line.unit || '' }}</span>
              <span :class="{ 'iod-line__remain': line.remain_qty > 0 }">
                欠 {{ formatQty(line.remain_qty) }}{{ line.unit || '' }}
              </span>
            </div>
            <div v-if="line.suggest_batch_no || line.suggest_location_name" class="iod-line__suggest">
              建议批次 {{ line.suggest_batch_no || '-' }} · 库位
              {{ line.suggest_location_name || '-' }}
            </div>
          </li>
        </ul>
      </section>
    </ZiwiStateView>

    <ZiwiActionBar
      v-if="state === 'ready' && hasExecuteRoute"
      :primary-text="canExecute ? '开始出库' : statusEntry.label"
      :primary-disabled="!canExecute"
      secondary-text="返回列表"
      @primary="goExecute"
      @secondary="router.push('/wms/issue-orders')"
    />
  </div>
</template>

<style scoped>
.iod-page {
  padding-bottom: calc(var(--ziwi-actionbar-h) + 16px);
  max-width: 980px;
  margin: 0 auto;
}

.iod-head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-touch-min);
  margin-bottom: var(--ziwi-gap-sm);
}
.iod-head__back {
  flex: none;
  width: var(--ziwi-touch-min);
  height: var(--ziwi-touch-min);
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
  font-size: 22px;
  line-height: 1;
  color: #495057;
  cursor: pointer;
}
.iod-head__main { flex: 1; min-width: 0; }
.iod-head__title { margin: 0; font-size: 16px; font-weight: 600; color: #212529; }
.iod-head__no { margin-top: 2px; }

.iod-card {
  background: #fff;
  border: 1px solid #e9ecef;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: var(--ziwi-gap-md, 12px);
}

.iod-grid { margin: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }
.iod-grid__row { min-width: 0; }
.iod-grid dt { font-size: 12px; color: #868e96; margin-bottom: 2px; }
.iod-grid dd { margin: 0; font-size: 14px; color: #212529; word-break: break-word; }

.iod-note {
  margin: 12px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f1f3f5;
  font-size: 13px;
  color: #495057;
}
.iod-note--warn {
  background: var(--ziwi-state-warning-bg);
  color: var(--ziwi-state-warning-fg);
  border: 1px solid var(--ziwi-state-warning-bd);
}

.iod-card__bar { display: flex; align-items: center; justify-content: space-between; }
.iod-card__title { margin: 0 0 8px; font-size: 15px; font-weight: 600; color: #212529; }
.iod-card__pending {
  font-size: 12px;
  color: var(--ziwi-state-warning-fg);
  background: var(--ziwi-state-warning-bg);
  border-radius: 10px;
  padding: 2px 8px;
}
.iod-empty { margin: 0; padding: 12px 0; color: #868e96; font-size: 13px; }

.iod-lines { list-style: none; margin: 0; padding: 0; }
.iod-line { padding: 10px 0; border-top: 1px solid #f1f3f5; }
.iod-line__main { display: flex; align-items: center; gap: 8px; }
.iod-line__no {
  flex: none;
  min-width: 22px;
  text-align: center;
  font-size: 12px;
  color: #868e96;
  background: #f1f3f5;
  border-radius: 4px;
  padding: 1px 4px;
}
.iod-line__name { flex: 1; min-width: 0; font-size: 14px; color: #212529; }
.iod-line__tag { flex: none; font-size: 11px; border-radius: 10px; padding: 2px 8px; }
.iod-line__tag--done {
  color: var(--ziwi-state-success-fg);
  background: var(--ziwi-state-success-bg);
}
.iod-line__tag--pending {
  color: var(--ziwi-state-warning-fg);
  background: var(--ziwi-state-warning-bg);
}
.iod-line__nums {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-top: 4px;
  font-size: 12px;
  color: #6c757d;
}
.iod-line__remain { color: var(--ziwi-state-danger-fg); }
.iod-line__suggest { margin-top: 2px; font-size: 12px; color: #868e96; }

/* H 形态：单列，标签与值上下排（412 视口两列会把值挤成竖排） */
:global(html[data-form-factor='H']) .iod-grid { grid-template-columns: 1fr; }
</style>
