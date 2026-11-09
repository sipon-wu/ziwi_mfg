<script setup lang="ts">
/**
 * 合装组套页（B-20）· MA020 合装工位现场用
 *
 * ## 现场动作序列（本页就是按这个顺序排的）
 * 1. 站着工单进来（从工单详情跳 `?wo=<id>&wo_no=<号>`），或现场扫工单号定位；
 * 2. 扫**定子码** → 扫完自动跳下一个位，不用点；
 * 3. 扫**转子码** → 两个码都齐了，组套按钮才可点；
 * 4. 点「组套」→ 后端合成一个成品码，本页大字显示，工人贴标；
 * 5. 点「继续下一台」→ 两个码清空、焦点回定子位，接着扫下一台。
 *
 * ## 为什么按钮必须两码齐才可点（不是点了再报错）
 * 现场规则是「**扫到才生效，以扫到合装为准**」——没有"提交半套"这一步。
 * 按钮可点 = 两个码都在，这条规则就被按钮本身表达了；让它可点再弹错误，
 * 等于先允许一次不存在的操作，再解释它不存在。
 *
 * ## 为什么成功后面板要留「组套构成」的查询入口
 * 组套是一次性动作，但事后核对是天天要做的（这台整机的定子/转子是哪两个码、
 * 某个部件码装进了哪台整机）。后端 `GET /wms/batches/{id}/composition` 两个方向
 * 都返回，如果界面不给入口，这条能力就等于不存在 —— B-14 的教训（接口在、
 * 入口不在，等于功能没做过）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { get, post, errorText } from '@/api/client'
import { useSubmitLock } from '@/composables/useSubmitLock'
import ZiwiScanField from '@/components/ziwi/ZiwiScanField.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'

interface ComposeResult {
  batch_id: number
  batch_no: string
  material_id: number
  material_code: string | null
  work_order_id: number
  wo_no: string | null
  parents: { batch_id: number; batch_no: string; material_code: string | null }[]
}

interface CompositionChild {
  id: number
  batch_no: string
  material_code: string | null
  batch_type: string | null
}

/** 工单定位方式：带 query 进来 = 从工单详情跳转；否则现场扫/输工单号 */
const route = useRoute()
const lock = useSubmitLock()

const woId = ref<number | null>(null)
const woNo = ref<string>('')
const woInput = ref<string>('')
const woError = ref('')

const statorNo = ref('')
const rotorNo = ref('')
const composeError = ref('')
const submitting = ref(false)
const result = ref<ComposeResult | null>(null)

const statorRef = ref<InstanceType<typeof ZiwiScanField> | null>(null)
const rotorRef = ref<InstanceType<typeof ZiwiScanField> | null>(null)

const canCompose = computed(
  () => !!woId.value && !!statorNo.value.trim() && !!rotorNo.value.trim() && !submitting.value,
)

/**
 * 把焦点挪到某个扫码位。
 *
 * ★ ZiwiScanField 没暴露 `focus()`，这里走 DOM 拿内部 input —— 刻意不改那个
 *   共用组件加 API：全站 7 处都在用它，为一个页面加接口等于把回归面扩大 7 倍。
 *   拿不到就静默，**不能因为"自动跳位失败"挡住扫码**（点一下照样能用）。
 */
function focusField(target: 'stator' | 'rotor'): void {
  const comp = (target === 'stator' ? statorRef.value : rotorRef.value) as any
  const input = comp?.$el?.querySelector?.('input') as HTMLInputElement | undefined
  input?.focus?.()
}

/** 从工单详情跳进来时，工单已经定死了，不再让人重选（避免组错单） */
onMounted(() => {
  const q = route.query
  if (q.wo) {
    woId.value = Number(q.wo) || null
    woNo.value = String(q.wo_no || q.wo)
  }
  focusField('stator')
})

/** 现场扫/手输工单号 → 精确匹配 wo_no（不拿模糊结果替人挑） */
async function resolveWorkOrder(code: string): Promise<void> {
  const target = (code || '').trim()
  woError.value = ''
  if (!target) return
  try {
    const res = await get<any>('/work-orders', { keyword: target, page_size: 20 })
    const items: any[] = res?.items || []
    const hit = items.find(x => x.wo_no === target)
    if (!hit) {
      woError.value = `找不到工单「${target}」`
      return
    }
    woId.value = hit.id
    woNo.value = hit.wo_no
    woInput.value = ''
    focusField('stator')
  } catch (e) {
    woError.value = errorText(e, '工单查询失败')
  }
}

function onStatorScan(code: string): void {
  statorNo.value = code
  // 扫完定子直接跳转子：少一次点击，且顺带防止"两个码扫进同一个框"
  focusField('rotor')
}

function onRotorScan(code: string): void {
  rotorNo.value = code
}

async function doCompose(): Promise<void> {
  if (!canCompose.value) return
  composeError.value = ''
  submitting.value = true
  try {
    // 锁键带上两个码：同一对码连点只发一次；不同码互不阻塞
    const data = await lock.run(`compose:${statorNo.value}:${rotorNo.value}`, () =>
      post<ComposeResult>('/wms/batches/compose', {
        work_order_id: woId.value,
        stator_no: statorNo.value.trim(),
        rotor_no: rotorNo.value.trim(),
      }),
    )
    result.value = data as ComposeResult
  } catch (e) {
    // 后端文案已经写得很具体（哪个码、什么原因），原样展示比"组套失败"有用得多
    composeError.value = errorText(e, '组套失败')
  } finally {
    submitting.value = false
  }
}

function nextOne(): void {
  result.value = null
  composeError.value = ''
  statorNo.value = ''
  rotorNo.value = ''
  focusField('stator')
}

/* ── 组套构成查询（事后核对：随意扫一个码，看它由什么组成 / 装进了谁）── */
const lookupNo = ref('')
const lookupError = ref('')
const lookupLoading = ref(false)
const lookupResult = ref<{
  batch: any
  children: CompositionChild[]
  parent: CompositionChild | null
} | null>(null)

async function doLookup(code: string): Promise<void> {
  const target = (code || '').trim()
  lookupError.value = ''
  lookupResult.value = null
  if (!target) return
  lookupLoading.value = true
  try {
    // ① 先按码找批次：唯一约束是 (租户, 物料, 码)，同码可挂不同物料
    const res = await get<any>('/wms/batches', { keyword: target, page_size: 20 })
    const rows: any[] = (res?.items || []).filter((x: any) => x.batch_no === target)
    if (!rows.length) {
      lookupError.value = `批次台账里没有「${target}」`
      return
    }
    if (rows.length > 1) {
      // 不替用户挑一条 —— 挑错了看到的父子关系是另一个物料的
      lookupError.value =
        `「${target}」命中 ${rows.length} 条批次（不同物料同码），请先在批次管理里核对`
      return
    }
    // ② 再查构成
    const comp = await get<any>(`/wms/batches/${rows[0].id}/composition`)
    lookupResult.value = {
      batch: comp?.batch || rows[0],
      children: comp?.children || [],
      parent: comp?.parent || null,
    }
  } catch (e) {
    lookupError.value = errorText(e, '查询失败')
  } finally {
    lookupLoading.value = false
  }
}
</script>

<template>
  <div class="bc-page">
    <header class="bc-head">
      <h1 class="bc-head__title">合装组套</h1>
      <p class="bc-head__sub">扫定子码 + 转子码 → 现场合成一个成品码</p>
    </header>

    <!-- ══════════ 工单 ══════════ -->
    <section class="bc-card">
      <h2 class="bc-card__title">工单</h2>
      <div v-if="woId" class="bc-wo">
        <ZiwiCodeText :code="woNo" label="工单号" size="md" />
        <span class="bc-wo__hint">成品物料按这张工单反查，组错单等于码贴错整机</span>
      </div>
      <template v-else>
        <van-field
          v-model="woInput"
          label="工单号"
          placeholder="扫工单号或手输后回车"
          clearable
          @keyup.enter="resolveWorkOrder(woInput)"
        />
        <p v-if="woError" class="bc-error" role="alert">{{ woError }}</p>
        <p v-else class="bc-hint">也可以从工单详情页点「合装组套」进来，那边会自动带上工单</p>
      </template>
    </section>

    <!-- ══════════ 两个扫码位 ══════════ -->
    <section class="bc-card">
      <h2 class="bc-card__title">部件码</h2>
      <ZiwiScanField
        ref="statorRef"
        label="定子码"
        object-name="定子码"
        :model-value="statorNo"
        :clear-on-scan="false"
        autofocus
        field-name="stator_no"
        @scan="onStatorScan"
      />
      <ZiwiScanField
        ref="rotorRef"
        label="转子码"
        object-name="转子码"
        :model-value="rotorNo"
        :clear-on-scan="false"
        field-name="rotor_no"
        @scan="onRotorScan"
      />
      <p class="bc-hint">
        扫到才生效：两个码都齐了按钮才可点，不做「缺一个也提交」。
      </p>
      <van-button
        class="bc-compose-btn"
        type="primary"
        block
        :loading="submitting"
        :disabled="!canCompose"
        @click="doCompose"
      >
        组套并生成成品码
      </van-button>
      <p v-if="composeError" class="bc-error" role="alert">{{ composeError }}</p>
    </section>

    <!-- ══════════ 结果：大字成品码 ══════════ -->
    <section v-if="result" class="bc-card bc-result" aria-live="polite">
      <h2 class="bc-card__title">组套成功 · 成品码</h2>
      <p class="bc-result__code" data-field="final_code">{{ result.batch_no }}</p>
      <p class="bc-result__meta">
        物料 {{ result.material_code || '—' }} · 工单 {{ result.wo_no || result.work_order_id }}
      </p>
      <ul class="bc-parents">
        <li v-for="p in result.parents" :key="p.batch_id" class="bc-parents__row">
          <span class="bc-parents__label">部件</span>
          <ZiwiCodeText :code="p.batch_no" :label="p.material_code || ''" size="sm" />
        </li>
      </ul>
      <van-button class="bc-next-btn" block plain type="primary" @click="nextOne">
        继续下一台
      </van-button>
    </section>

    <!-- ══════════ 组套构成查询 ══════════ -->
    <section class="bc-card">
      <h2 class="bc-card__title">查组套构成</h2>
      <ZiwiScanField
        label="任意码"
        object-name="批次码"
        :model-value="lookupNo"
        field-name="lookup_no"
        @scan="doLookup"
      />
      <p v-if="lookupLoading" class="bc-hint">查询中…</p>
      <p v-if="lookupError" class="bc-error" role="alert">{{ lookupError }}</p>
      <div v-if="lookupResult" class="bc-lookup">
        <div class="bc-lookup__row">
          <span class="bc-lookup__label">本码</span>
          <ZiwiCodeText :code="lookupResult.batch?.batch_no" size="sm" />
        </div>
        <div class="bc-lookup__row">
          <span class="bc-lookup__label">装进了</span>
          <ZiwiCodeText
            v-if="lookupResult.parent"
            :code="lookupResult.parent.batch_no"
            size="sm"
          />
          <span v-else class="bc-lookup__none">尚未组套</span>
        </div>
        <div class="bc-lookup__row">
          <span class="bc-lookup__label">由这些组成</span>
          <span v-if="!lookupResult.children.length" class="bc-lookup__none">无部件记录</span>
          <ul v-else class="bc-lookup__kids">
            <li v-for="c in lookupResult.children" :key="c.id">
              <ZiwiCodeText :code="c.batch_no" :label="c.material_code || ''" size="sm" />
            </li>
          </ul>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.bc-page {
  padding: var(--ziwi-gap-md);
  padding-bottom: calc(var(--ziwi-gap-xxl, 48px) + env(safe-area-inset-bottom, 0px));
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-md);
}

.bc-head__title {
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 600;
  color: var(--ziwi-text-primary);
}

.bc-head__sub {
  margin: var(--ziwi-gap-xs) 0 0;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.bc-card {
  background: var(--ziwi-bg-surface);
  border-radius: var(--ziwi-radius-md);
  padding: var(--ziwi-gap-md);
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-sm);
}

.bc-card__title {
  margin: 0;
  font-size: var(--ziwi-font-size-md);
  font-weight: 600;
  color: var(--ziwi-text-primary);
}

.bc-wo {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ziwi-gap-sm);
}

.bc-wo__hint,
.bc-hint {
  margin: 0;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.bc-error {
  margin: 0;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-danger, #c0261c);
  line-height: var(--ziwi-lineheight-normal);
}

/* 组套是本章最高频的一次点击：热区走手套档令牌，不写死尺寸 */
.bc-compose-btn,
.bc-next-btn {
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.bc-result {
  border: 1px solid var(--ziwi-brand, #2563eb);
}

/* 成品码要给站在一米外的人念得清：等宽 + 大字号 + 字距 */
.bc-result__code {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ziwi-brand, #2563eb);
  word-break: break-all;
}

.bc-result__meta {
  margin: 0;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.bc-parents {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-xs);
}

.bc-parents__row,
.bc-lookup__row {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-row-min-h);
}

.bc-parents__label,
.bc-lookup__label {
  flex: 0 0 auto;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.bc-lookup__kids {
  list-style: none;
  margin: 0;
  padding: 0;
}

.bc-lookup__none {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

/* 手持档（H）：窄屏把「标签 + 码」改成上下两行，避免码被挤成省略号 */
:global(html[data-form-factor='H']) .bc-parents__row,
:global(html[data-form-factor='H']) .bc-lookup__row {
  flex-wrap: wrap;
}

:global(html[data-form-factor='H']) .bc-result__code {
  font-size: 26px;
}
</style>
