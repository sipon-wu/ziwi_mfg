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
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post, errorText } from '@/api/client'
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

/** 报工小组筛选。`null` = 不筛（"全部"）。
 *
 * ★ 为什么放在报工台上而不是只放配置页：车间的人按**组**找活
 *  （"今天我们前段组要干哪几道"），不按工单号找。没有这一层，
 *  前段组的人得在有 21 道工序的工单里翻自己那 5 道。 */
const groupFilter = ref<number | null>(null)
const groups = ref<{ id: number; name: string }[]>([])

async function fetchGroups() {
  try {
    const res = await get<{ items?: { id: number; name: string; is_active?: boolean }[] }>(
      '/operation-groups',
      { params: { page: 1, page_size: 100, is_active: true } },
    )
    groups.value = (res.items || []).map((g) => ({ id: g.id, name: g.name }))
  } catch (e) {
    // 分组读不出来不该让整个任务台打不开 —— 它只是筛选器。
    console.warn('[WorkReportList] 获取报工小组失败', e)
    groups.value = []
  }
}

function pickGroup(id: number | null) {
  if (groupFilter.value === id) return
  groupFilter.value = id
  fetchPage(true)
}

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
      group_id: groupFilter.value ?? undefined,
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

/* ── 扫码过站（C-108）─────────────────────────────────────────────
 *
 * 扫码枪在系统眼里就是一个**键盘**：一串字符 + 回车。所以这里不做任何
 * 设备对接 —— 一个输入框 + 回车就够，现场没有枪时用键盘敲工单号，
 * 行为与扫码完全一致（Kane 原话："扫码和输入没区别，可以模拟"）。
 *
 * 码怎么拆（工单号 / 工单号#工序编码 / 工单号#工序序号）**由后端解析**，
 * 前端不猜：这是业务规则，写在两处早晚不一致。
 */
const scanCode = ref('')
const scanning = ref(false)
const scanInput = ref<HTMLInputElement | null>(null)

function focusScan() {
  // 扫码枪连扫的前提是焦点一直在输入框上。点过别处（翻页、切 tab）之后
  // 就扫不进去了，而现场不会意识到是焦点问题 —— 会以为枪坏了。
  nextTick(() => scanInput.value?.focus())
}

async function doScan() {
  const code = scanCode.value.trim()
  if (!code || scanning.value) return
  scanning.value = true
  try {
    const res = await post<{ message?: string }>('/work-orders/steps/execute', { code })
    showToast(res?.message || `${code} 已过站`)
    await fetchPage(true)
  } catch (e) {
    // ★ 失败也必须清空输入框：扫码枪的动作是「清空 + 输入 + 回车」，
    //   框里留着旧码时，下一次扫码会**拼在旧码后面**，必然再报一次
    //   "认不出来" —— 现场会以为条码印坏了，跑去重打一张，问题却永远不消失。
    //   把扫到的内容放进提示里，现场仍然看得到刚才扫的是什么。
    showToast({ message: `${code}：${errorText(e, '过站失败')}`, duration: 4000 })
  } finally {
    scanCode.value = ''
    scanning.value = false
    focusScan()
  }
}

onMounted(() => {
  fetchGroups()
  fetchPage(true)
  focusScan()
})
</script>

<template>
  <div class="wrs">
    <van-nav-bar title="报工管理" right-text="整单报工" @click-right="goWholeOrder" />

    <!-- 扫码过站（C-108）：扫码枪 = 键盘 + 回车，所以这里就是一个输入框。
         放在最上面而不是收进筛选栏 —— 车间的主动作是"扫一下"，搜索在下面负责"查"。 -->
    <div class="wrs-scan">
      <input
        ref="scanInput"
        v-model="scanCode"
        class="wrs-scan__input"
        type="text"
        autocomplete="off"
        placeholder="扫工单码 / 输入工单号，回车过站"
        :disabled="scanning"
        @keyup.enter="doScan"
      />
      <button
        type="button"
        class="wrs-scan__btn"
        :disabled="scanning || !scanCode.trim()"
        @click="doScan"
      >{{ scanning ? '过站中…' : '过站' }}</button>
    </div>

    <van-tabs :active="tab" @change="switchTab">
      <van-tab title="待作业" name="open" />
      <van-tab title="已完工" name="completed" />
    </van-tabs>

    <!-- 小组筛选：车间按"我们组"找活，不按工单号找。
         只有真配过分组时才显示整条筛选栏，否则多一行空白挤占首屏。 -->
    <div v-if="groups.length" class="wrs-groups">
      <button
        type="button"
        class="wrs-groups__chip"
        :class="{ on: groupFilter === null }"
        @click="pickGroup(null)"
      >全部</button>
      <button
        v-for="g in groups"
        :key="g.id"
        type="button"
        class="wrs-groups__chip"
        :class="{ on: groupFilter === g.id }"
        @click="pickGroup(g.id)"
      >{{ g.name }}</button>
    </div>

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

        <div v-if="s.groups && s.groups.length" class="wrs-row__groups">
          <span v-for="g in s.groups" :key="g.id" class="wrs-row__group-tag">
            {{ g.name || g.code || '未命名小组' }}
          </span>
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

/* 扫码过站：整条是"输入框 + 过站按钮"，输入框吃满剩余宽度。
   热区用 --ziwi-touch-min（车间触屏，戴手套也能点中），
   高度不写死数字 —— 三档 W/T/H 由 formFactor 统一决定。 */
.wrs-scan {
  display: flex;
  gap: var(--ziwi-gap-sm);
  align-items: stretch;
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border);
}

.wrs-scan__input {
  flex: 1 1 auto;
  min-width: 0;
  min-height: var(--ziwi-touch-min);
  padding: 0 var(--ziwi-gap-sm);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-primary);
  font-size: var(--ziwi-font-size-md);
}

.wrs-scan__input:focus {
  outline: none;
  border-color: var(--ziwi-primary);
}

.wrs-scan__btn {
  flex: 0 0 auto;
  min-height: var(--ziwi-touch-min);
  padding: 0 var(--ziwi-gap-md);
  border: none;
  border-radius: var(--ziwi-radius-sm);
  background: var(--ziwi-primary);
  color: #fff;
  font-size: var(--ziwi-font-size-md);
  font-weight: 600;
}

.wrs-scan__btn:disabled {
  opacity: 0.5;
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

/* 小组筛选条：横向滚动，热区 40（车间手势）。
   选中态同时改背景与边框，不只改文字色 —— 产线屏色偏时只变色等于没变。 */
.wrs-groups {
  display: flex;
  gap: var(--ziwi-gap-sm);
  overflow-x: auto;
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md) 0;
  -webkit-overflow-scrolling: touch;
}

.wrs-groups__chip {
  flex: 0 0 auto;
  min-height: 36px;
  padding: 0 14px;
  border-radius: 18px;
  border: 1px solid var(--ziwi-border);
  background: var(--ziwi-bg-white);
  color: var(--ziwi-text-primary);
  font-size: var(--ziwi-font-size-sm);
}

.wrs-groups__chip.on {
  border-color: var(--van-primary-color, #1989fa);
  background: rgba(25, 137, 250, 0.1);
  font-weight: 600;
}

.wrs-row__groups {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.wrs-row__group-tag {
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--ziwi-bg-hover, #f1f5f9);
  color: var(--ziwi-text-secondary);
  font-size: 12px;
}
</style>
