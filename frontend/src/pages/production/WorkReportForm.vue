<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast, showDialog } from 'vant'
import ZiwiSelect from '@/components/ziwi/ZiwiSelect.vue'
import dayjs from 'dayjs'
import type { WorkOrder, PaginatedResponse } from '@/types'

const router = useRouter()

const DEFECT_REASONS = ['尺寸超差', '表面缺陷', '装配不良', '材料问题', '设备异常', '其他']
const REPORT_MODES = [
  { value: 'personal', label: '个人报工' },
  { value: 'team', label: '小组报工' },
  { value: 'equipment', label: '设备报工' },
]

const form = ref({
  report_mode: 'personal',
  work_order_id: '' as string | number,
  report_date: dayjs().format('YYYY-MM-DD'),
  operation_code: '',
  operation_name: '',
  input_qty: 0,
  output_qty: 0,
  scrap_qty: 0,
  defect_reasons: [] as string[],
  defect_reason: '',
  labor_hours: 0,
  machine_hours: 0,
  start_time: '',
  end_time: '',
  unit_price: 0,
})
const orders = ref<WorkOrder[]>([])
const submitting = ref(false)

// 可报工的工单状态：草稿未下达、已关闭/已作废均已收口（后端会 400，这里先过滤）
const REPORTABLE_STATUS = ['released', 'in_progress', 'paused']
const reportableOrders = computed(() => orders.value.filter(o => REPORTABLE_STATUS.includes(o.wo_status)))
// 选项用 `label` 而非 Vant 滚轮的 `text`：ZiwiSelect 只认 `label/value`（内部再归一化）
const orderOptions = computed(() =>
  reportableOrders.value.map(o => ({ label: `${o.wo_no} - ${o.product_name}`, value: o.id }))
)

// 工价自动计算（前端计算展示；有工价接口时再对接）
const total_price = computed(() => {
  const qty = Number(form.value.output_qty) || 0
  const price = Number(form.value.unit_price) || 0
  return Math.round(qty * price * 100) / 100
})

onMounted(async () => {
  try {
    const r = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 100 })
    orders.value = r.items || []
  } catch (e) {
    console.warn('[WorkReportForm] 获取工单列表失败', e)
  }
  observeSections()
})

/* ------------------------------------------------------------------ *
 * 单页分组 + 锚点跳转（UE §3.2：14 个字段不分步，靠分区导航缩短感知长度）
 * ------------------------------------------------------------------ */

/** 分区定义：id 直接落到 van-cell-group 的根元素上，供滚动定位使用 */
const SECTIONS = [
  { id: 'sec-order', label: '工单工序' },
  { id: 'sec-qty', label: '数量不良' },
  { id: 'sec-time', label: '打卡工时' },
  { id: 'sec-price', label: '工价' },
] as const

const activeSection = ref<string>(SECTIONS[0].id)

/** 是否走平滑滚动：用户开了「减少动态效果」就必须切换成瞬时定位 */
const reduceMotion = (): boolean =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * 滚到某个分区。
 *
 * `scroll-margin-top` 在样式里给分区留了导航条的高度，
 * 否则吸顶导航会把分区标题盖住——"跳过去但看不见"比不跳更糟。
 */
function goSection(id: string): void {
  const el = document.getElementById(id)
  if (!el) return
  activeSection.value = id
  el.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' })
}

/** 首个未填的必填项（用于「跳到未填」） */
const firstMissing = computed<{ label: string; section: string } | null>(() => {
  if (!form.value.work_order_id) return { label: '工单', section: 'sec-order' }
  if (!form.value.report_date) return { label: '报工日期', section: 'sec-order' }
  if (!form.value.output_qty) return { label: '合格数量', section: 'sec-qty' }
  return null
})

function jumpToMissing(): void {
  const miss = firstMissing.value
  if (miss) goSection(miss.section)
}

let observer: IntersectionObserver | null = null

/**
 * 用 IntersectionObserver 跟踪当前所在分区。
 *
 * 监听 scroll 再逐帧比较各分区 offsetTop 会在长表单上每帧触发布局计算；
 * observer 只在跨越阈值时回调，触屏滚动时更稳。
 */
function observeSections(): void {
  if (typeof IntersectionObserver === 'undefined') return
  observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (visible[0]?.target.id) activeSection.value = visible[0].target.id
    },
    { rootMargin: '-88px 0px -55% 0px', threshold: 0 },
  )
  SECTIONS.forEach((s) => {
    const el = document.getElementById(s.id)
    if (el) observer?.observe(el)
  })
}

onBeforeUnmount(() => observer?.disconnect())

async function handleSubmit() {
  // 缺必填时直接把用户滚到那一段：只弹一句「请先选择工单」，
  // 在小屏上他仍要自己翻回去找，等于把定位成本推给了现场
  const miss = firstMissing.value
  if (miss) {
    goSection(miss.section)
    showToast(`请先填写${miss.label}`)
    return
  }
  const payload = {
    ...form.value,
    defect_reason: [...form.value.defect_reasons].join('、') || form.value.defect_reason || '',
    start_time: form.value.start_time || null,
    end_time: form.value.end_time || null,
  }
  submitting.value = true
  try {
    const res = await post<{ warnings?: string[] }>('/work-reports', payload)
    // 后端的 warnings 必须露出来。最典型的一条是 B-1 的「本次报工工序不是末道
    // 工序，产出计入在制、不计入完工数」—— 报工成功了但完工数没动，不解释的话
    // 现场会以为是系统没记上，然后再报一遍（报工没有幂等键）。
    const warns = res?.warnings || []
    if (warns.length) {
      await showDialog({
        title: '报工已提交，但请注意',
        message: warns.map((w) => `· ${w}`).join('\n\n'),
      })
    } else {
      showToast('报工提交成功')
    }
    router.push('/work-reports')
  } catch (e: any) {
    // 后端对"数量为 0 / 工单未下达"等给了明确文案，直接展示，不要吞成"提交失败"
    const d = e?.response?.data?.detail
    showToast(typeof d === 'object' && d?.message ? d.message : '提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <van-nav-bar title="报工录入" left-arrow @click-left="router.back()" />

    <!-- 分区导航：吸顶。14 个字段一页到底时，靠它把"还要填多少"变成可见的 4 段 -->
    <nav class="wrf-nav" aria-label="报工表单分区">
      <button
        v-for="s in SECTIONS"
        :key="s.id"
        type="button"
        class="wrf-nav__chip"
        :class="{ 'wrf-nav__chip--active': activeSection === s.id }"
        :aria-current="activeSection === s.id ? 'true' : undefined"
        @click="goSection(s.id)"
      >
        {{ s.label }}
      </button>
      <button
        v-if="firstMissing"
        type="button"
        class="wrf-nav__chip wrf-nav__chip--jump"
        @click="jumpToMissing"
      >
        跳到未填 · {{ firstMissing.label }}
      </button>
    </nav>

    <van-form @submit="handleSubmit" class="wrf-form">
      <!-- ① 工单工序 -->
      <van-cell-group id="sec-order" title="① 工单工序">
        <van-field name="report_mode" label="报工模式">
          <template #input>
            <van-radio-group v-model="form.report_mode" direction="horizontal">
              <van-radio v-for="m in REPORT_MODES" :key="m.value" :name="m.value">{{ m.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <!-- R1：选择器不进表单流，改浮层（原 van-picker 内联进 #input，滚轮在触屏上极易误触） -->
        <ZiwiSelect
          v-model="form.work_order_id"
          field-name="work_order_id"
          label="工单"
          required
          :clearable="false"
          :options="orderOptions"
          object-name="工单"
          placeholder="选择工单"
        />
        <van-field v-model="form.report_date" label="报工日期" type="date" :rules="[{required:true}]" />
        <van-field v-model="form.operation_code" label="工序编码" />
        <van-field v-model="form.operation_name" label="工序名称" />
      </van-cell-group>

      <!-- ② 数量与不良 -->
      <van-cell-group id="sec-qty" title="② 数量与不良">
        <van-field v-model.number="form.input_qty" label="投入数量" type="digit" />
        <van-field v-model.number="form.output_qty" label="合格数量" type="digit" :rules="[{required:true}]" />
        <van-field v-model.number="form.scrap_qty" label="不良数量" type="digit" />
        <van-field name="defect_reasons" label="不良原因">
          <template #input>
            <van-checkbox-group v-model="form.defect_reasons" direction="horizontal">
              <van-checkbox v-for="r in DEFECT_REASONS" :key="r" :name="r" shape="square">{{ r }}</van-checkbox>
            </van-checkbox-group>
          </template>
        </van-field>
      </van-cell-group>

      <!-- ③ 打卡与工时 -->
      <van-cell-group id="sec-time" title="③ 打卡与工时">
        <van-field v-model="form.start_time" label="开始时间" type="time" placeholder="HH:mm" />
        <van-field v-model="form.end_time" label="结束时间" type="time" placeholder="HH:mm" />
        <van-field v-model.number="form.labor_hours" label="工时(小时)" type="digit" />
        <van-field v-model.number="form.machine_hours" label="机时(小时)" type="digit" />
      </van-cell-group>

      <!-- ④ 工价 -->
      <van-cell-group id="sec-price" title="④ 工价">
        <van-field v-model.number="form.unit_price" label="工价(元/件)" type="digit" placeholder="0" />
        <van-cell title="应计工价" :value="`¥ ${total_price}`" />
      </van-cell-group>

      <div class="wrf-submit">
        <van-button round block type="primary" native-type="submit" :loading="submitting">提交报工</van-button>
      </div>
    </van-form>
  </div>
</template>

<style scoped>
.wrf-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  gap: var(--ziwi-touch-gap-adj);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  overflow-x: auto;
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border);
  -webkit-overflow-scrolling: touch;
}

.wrf-nav__chip {
  flex: none;
  min-height: var(--ziwi-touch-min);
  padding: 0 var(--ziwi-gap-md);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-round);
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-primary);
  font-size: var(--ziwi-font-size-md);
  white-space: nowrap;
  cursor: pointer;
  /* 按下反馈走 A1 令牌，不用裸时长 */
  transition: background var(--ziwi-motion-tap-duration) var(--ziwi-motion-tap-easing),
    border-color var(--ziwi-motion-tap-duration) var(--ziwi-motion-tap-easing);
}

.wrf-nav__chip--active {
  border-color: var(--ziwi-primary);
  background: var(--ziwi-primary-light);
  color: var(--ziwi-primary);
  font-weight: 600;
}

.wrf-nav__chip--jump {
  border-style: dashed;
  border-color: var(--ziwi-warning);
  color: var(--ziwi-warning);
}

html[data-hover='on'] .wrf-nav__chip:hover {
  background: var(--ziwi-bg-light);
}

.wrf-form {
  padding-bottom: var(--ziwi-gap-lg);
}

/* 分区留出吸顶导航的高度，锚点跳转后标题不会被盖住 */
.wrf-form > .van-cell-group {
  scroll-margin-top: calc(var(--ziwi-actionbar-h) + var(--ziwi-gap-sm));
}

.wrf-form > .van-cell-group + .van-cell-group {
  margin-top: var(--ziwi-gap-md);
}

.wrf-submit {
  margin: var(--ziwi-gap-lg) var(--ziwi-gap-md);
}
</style>
