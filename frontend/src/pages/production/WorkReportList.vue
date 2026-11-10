<script setup lang="ts">
/**
 * 报工管理 = 工序任务台。
 *
 * ## 为什么行对象是「工单 × 工序」而不是「报工记录」
 *
 * `work_reports` 记的是**已经发生的事**（staging 上 5629 条）。拿它当列表，
 * 车间看到的是台账：干过的活按时间倒序堆在一起，而"我今天该干哪道"一条都没有。
 * 更麻烦的是同一张 21 道工序的单只要报过一次就出现在列表里，剩下 20 道
 * 在界面上完全不存在 —— 于是报工只能靠"新建 → 手输工序编码"，
 * 编码打错不会报错，只会把产量记到另一道工序上。
 *
 * 2026-11-10 起列表就是**全部工序**：每行带计划/已报数量、是否在作业、
 * 阻塞与缺料标记，点进去是这道工序的报工页，每道工序都能报。
 *
 * ## 两个 tab 的取舍
 *
 * 默认「待作业」，不是「全部」。这是车间当天要看的清单，不是工序总账：
 * 把已完工的一起倒出来是上千行，第一屏全是干完的活，列表越长越没人看。
 * 已完工的仍在「已完工」tab 里可查可补报（不隐藏）。
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import { statusTagOf } from '@/composables/useStatusTag'
import type { WorkStep, PaginatedResponse } from '@/types'

const router = useRouter()

const PAGE_SIZE = 20
const tab = ref<'open' | 'completed'>('open')
const steps = ref<WorkStep[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const finished = ref(false)
const keyword = ref('')

/** 缺料标记：`material_check_status` 挂在工单上，`failed` 才是真缺料 */
const isShortOfMaterial = (s: WorkStep) => s.material_check_status === 'failed'

async function fetchPage(reset = false) {
  if (reset) {
    page.value = 1
    finished.value = false
    steps.value = []
  }
  loading.value = true
  try {
    const res = await get<PaginatedResponse<WorkStep>>('/work-orders/steps', {
      page: page.value,
      page_size: PAGE_SIZE,
      scope: tab.value,
      keyword: keyword.value || undefined,
    })
    const items = res.items || []
    steps.value = page.value === 1 ? items : [...steps.value, ...items]
    total.value = res.total || 0
    // ★ 用「本页拿到的条数 < 每页条数」判结束，而不是 `steps.length >= total`：
    //   total 会随后台新报工变化，一旦 total 变大，列表就永远停在"还有下一页"
    //   却再也 load 不出东西（底部一直转圈）。
    finished.value = items.length < PAGE_SIZE
    if (!finished.value) page.value += 1
  } catch (e) {
    console.warn('[WorkReportList] 获取工序任务失败', e)
    finished.value = true
  } finally {
    loading.value = false
  }
}

function switchTab(name: string | number) {
  tab.value = name === 'completed' ? 'completed' : 'open'
  fetchPage(true)
}

onMounted(() => fetchPage(true))

/** 点行进这道工序的报工页 —— 工单与工序都由参数带过去，现场不用选也不用填 */
function openStep(s: WorkStep) {
  router.push({
    path: '/work-reports/create',
    query: { order_id: String(s.work_order_id), step_seq: String(s.step_seq) },
  })
}

/** 兜底入口：没挂工艺路线的老单按整单报工（合法形态，不是脏数据） */
function goWholeOrder() {
  router.push('/work-reports/create')
}
</script>

<template>
  <div class="wrs">
    <van-nav-bar title="报工管理" right-text="整单报工" @click-right="goWholeOrder" />

    <van-tabs :active="tab" @change="switchTab">
      <van-tab title="待作业" name="open" />
      <van-tab title="已完工" name="completed" />
    </van-tabs>

    <van-search
      v-model="keyword"
      placeholder="搜工序 / 工单号 / 产品"
      @search="fetchPage(true)"
      @clear="fetchPage(true)"
    />

    <div class="wrs__count">共 {{ total }} 道工序</div>

    <van-list
      v-model:loading="loading"
      :finished="finished"
      finished-text="没有更多了"
      @load="fetchPage()"
    >
      <button
        v-for="s in steps"
        :key="s.id"
        type="button"
        class="wrs-row"
        :class="{ 'wrs-row--blocked': s.blocked }"
        @click="openStep(s)"
      >
        <div class="wrs-row__head">
          <span class="wrs-row__seq">{{ s.step_seq }}</span>
          <span class="wrs-row__op">{{ s.operation_name || s.operation_code || '未命名工序' }}</span>
          <span class="wrs-row__tag" :class="statusTagOf('work_order_step', s.status).className">
            <van-icon :name="statusTagOf('work_order_step', s.status).icon" />
            {{ statusTagOf('work_order_step', s.status).label }}
          </span>
        </div>

        <div class="wrs-row__meta">
          {{ s.wo_no || `#${s.work_order_id}` }} · {{ s.product_name || '—' }}
        </div>

        <div class="wrs-row__meta">
          工作中心：{{ s.wc_name || '未指定' }}
          <template v-if="s.operation_code"> · 工序码 {{ s.operation_code }}</template>
        </div>

        <div class="wrs-row__qty">
          <span class="wrs-row__qty-main">已报 <b>{{ s.output_qty }}</b> / 计划 {{ s.planned_qty || '—' }}</span>
          <span v-if="s.scrap_qty" class="wrs-row__qty-scrap">不良 {{ s.scrap_qty }}</span>
          <span v-if="s.report_count" class="wrs-row__qty-cnt">{{ s.report_count }} 次报工</span>
        </div>

        <div v-if="s.blocked || isShortOfMaterial(s)" class="wrs-row__flags">
          <span v-if="s.blocked" class="wrs-flag wrs-flag--danger">
            <van-icon name="warning-o" /> 安灯未关闭
          </span>
          <span v-if="isShortOfMaterial(s)" class="wrs-flag wrs-flag--warning">
            <van-icon name="cart-o" /> 缺料
          </span>
        </div>
      </button>
    </van-list>

    <van-empty v-if="!loading && !steps.length" description="没有待作业的工序" />
  </div>
</template>

<style scoped>
.wrs {
  padding-bottom: var(--ziwi-gap-lg);
}

.wrs__count {
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  color: var(--ziwi-text-secondary);
  font-size: var(--ziwi-font-size-sm);
}

/* 行是 button：整块可点，热区远大于一个"报工"按钮。
   车间戴手套点小按钮容易连续点空，整行可点才稳。 */
.wrs-row {
  display: block;
  width: calc(100% - var(--ziwi-gap-md) * 2);
  min-height: var(--ziwi-touch-min);
  margin: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  padding: var(--ziwi-gap-md);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-md);
  background: var(--ziwi-bg-white);
  text-align: left;
  cursor: pointer;
  transition: background var(--ziwi-motion-tap-duration) var(--ziwi-motion-tap-easing);
}

.wrs-row--blocked {
  border-color: var(--ziwi-state-danger-bd);
}

.wrs-row__head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
}

.wrs-row__seq {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 24px;
  border-radius: var(--ziwi-radius-round);
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-secondary);
  font-size: var(--ziwi-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.wrs-row__op {
  flex: 1;
  overflow: hidden;
  color: var(--ziwi-text-primary);
  font-size: var(--ziwi-font-size-lg);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wrs-row__tag {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0 var(--ziwi-gap-sm);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  font-size: var(--ziwi-font-size-sm);
  line-height: 20px;
}

.wrs-row__meta {
  margin-top: 2px;
  overflow: hidden;
  color: var(--ziwi-text-secondary);
  font-size: var(--ziwi-font-size-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wrs-row__qty {
  display: flex;
  align-items: baseline;
  gap: var(--ziwi-gap-md);
  margin-top: var(--ziwi-gap-sm);
  font-size: var(--ziwi-font-size-md);
  font-variant-numeric: tabular-nums;
}

.wrs-row__qty-main b {
  font-size: var(--ziwi-font-size-lg);
  color: var(--ziwi-text-primary);
}

.wrs-row__qty-scrap {
  color: var(--ziwi-state-danger-fg);
}

.wrs-row__qty-cnt {
  color: var(--ziwi-text-secondary);
  font-size: var(--ziwi-font-size-sm);
}

.wrs-row__flags {
  display: flex;
  gap: var(--ziwi-gap-sm);
  margin-top: var(--ziwi-gap-sm);
}

.wrs-flag {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0 var(--ziwi-gap-sm);
  border-radius: var(--ziwi-radius-sm);
  font-size: var(--ziwi-font-size-sm);
}

.wrs-flag--danger {
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
}

.wrs-flag--warning {
  background: var(--ziwi-state-warning-bg);
  color: var(--ziwi-state-warning-fg);
}

html[data-hover='on'] .wrs-row:hover {
  background: var(--ziwi-bg-light);
}
</style>
