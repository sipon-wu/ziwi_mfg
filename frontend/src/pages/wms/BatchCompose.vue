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
  /** 前缀来源：dict = 字典 trace_code_rule 配的（方案书 §2.1 为 TC）；fallback = 没配 */
  prefix_source?: 'dict' | 'fallback'
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
  // 换码重查时把拆解确认区收回去：否则上一台的「确认拆解」按钮会留在新码下面，
  // 手快点下去拆的就是另一台机器。
  decomposeOpen.value = false
  decomposeReason.value = ''
  decomposeError.value = ''
  decomposeDone.value = ''
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

/* ── 返修拆解（C-97）────────────────────────────────────────────
 *
 * ## 为什么入口放在这里，而不是列表页每行一个按钮
 *
 * 拆解的对象一定是**已经组套过的成品码**。列表页上绝大多数码没有子件，
 * 每行放一个按钮，99% 的人点下去只会得到"没有组套关系"的报错 ——
 * 那不是入口，那是噪音。
 *
 * 这里的位置是"查完成分、眼看着那台机器由哪两个件组成、决定要换掉"，
 * 拆解动作在语义上就长在这个位置。
 *
 * ## 为什么要点两下
 *
 * 第一次点只是**展开确认区**（把将要解除的部件码逐条摆出来），第二次才真拆。
 * 拆解会改追溯链，一步到位的按钮在车间的触摸屏上迟早被误触 ——
 * 而误触的后果是那台机器的构成记录被清掉。
 */
const decomposeOpen = ref(false)
const decomposeReason = ref('')
const decomposeError = ref('')
const decomposeDone = ref('')
const decomposeBusy = ref(false)

/** 只有「成品码 + 确实有子件」才给拆解入口 —— 其余情况按钮本身就是误导 */
const canDecompose = computed(
  () => !!lookupResult.value
    && lookupResult.value.batch?.batch_type === 'final'
    && lookupResult.value.children.length > 0,
)

async function doDecompose(): Promise<void> {
  const r = lookupResult.value
  if (!r?.batch?.id) return
  const reason = decomposeReason.value.trim()
  if (reason.length < 2) {
    decomposeError.value = '请填写拆解原因（返修单号或换件说明）'
    return
  }
  decomposeError.value = ''
  decomposeBusy.value = true
  try {
    const data = await post<any>(`/wms/batches/${r.batch.id}/decompose`, { reason })
    decomposeOpen.value = false
    decomposeReason.value = ''
    // ★ 重查构成，不在本地把 children 置空：本地改状态等于界面自己编事实，
    //   下次刷新又变回来，中间那段时间看到的都是假的。
    await doLookup(r.batch.batch_no)
    // ★ 成功提示必须放在 doLookup **之后**：doLookup 开头会清空 decomposeDone
    //   （换码时要清），先设再查等于设了个立刻被抹掉的提示 —— 用户看不到任何反馈，
    //   只会怀疑"到底拆没拆"。2026-11-09 浏览器探针 D1 抓到的就是这个。
    decomposeDone.value =
      `已解除 ${data?.released_count ?? 0} 个部件码，可以重新组套了`
  } catch (e) {
    // 后端文案已经说清是哪一步（不是成品码 / 没有组套 / 已入库），原样展示
    decomposeError.value = errorText(e, '拆解失败')
  } finally {
    decomposeBusy.value = false
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
      <!-- ★ 兜底前缀必须显形：方案书 §2.1 是 TC-YYYYMMDD-流水号，
           没配字典时系统用中性兜底（F），码照样生成、标签照样打得出来 ——
           等主机厂 MES 解析失败才发现就晚了。提示给出可执行的下一步。 -->
      <p v-if="result.prefix_source === 'fallback'" class="bc-warn" role="alert">
        当前用的是<strong>兜底前缀</strong>，与方案书 §2.1 的 <code>TC-YYYYMMDD-流水号</code> 不一致。
        请让管理员在字典 <code>trace_code_rule</code> 里配置成品码前缀 TC。
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

        <!-- ── 拆解成功提示 ──
             ★ 必须放在 `canDecompose` 的 **外面**：拆完之后子件就空了，
               `canDecompose` 立刻变 false，整个拆解块会消失 ——
               提示放在块里面，等于拆成功的那一刻自己把回执一起删掉，
               用户看不到任何反馈（2026-11-09 探针 D1 抓到的就是这个）。 -->
        <p v-if="decomposeDone" class="bc-decompose__done" role="status">
          {{ decomposeDone }}
        </p>

        <!-- ── 返修拆解（C-97）────────────────────────────────────────
             `compose` 撞到「已组套的部件码」会报「不能重复组套（返修请先拆解）」，
             这句话在 2026-11-09 之前指向一个不存在的功能 —— 返修要换件时，
             那个部件码永久绑死在旧成品上。入口就放在"看清成分之后"。
             两段式是刻意的：第一下只展开确认区，第二下才真拆。 -->
        <div v-if="canDecompose" class="bc-decompose">
          <template v-if="!decomposeOpen">
            <van-button
              class="bc-decompose__open"
              block
              plain
              type="warning"
              @click="decomposeOpen = true"
            >
              返修拆解（解除这 {{ lookupResult.children.length }} 个部件码）
            </van-button>
          </template>
          <template v-else>
            <p class="bc-decompose__warn" role="alert">
              将解除：<strong>
                {{ lookupResult.children.map(c => c.batch_no).join(' / ') }}
              </strong>
              。解除后成品码本身仍有效，但这些部件码会变成「未组套」，可重新组套。
              此操作会写入审计留痕。
            </p>
            <van-field
              v-model="decomposeReason"
              label="拆解原因"
              placeholder="返修单号或换件说明（必填）"
              maxlength="200"
              show-word-limit
            />
            <p v-if="decomposeError" class="bc-error" role="alert">{{ decomposeError }}</p>
            <div class="bc-decompose__actions">
              <van-button block plain :disabled="decomposeBusy" @click="decomposeOpen = false">
                取消
              </van-button>
              <van-button
                block
                type="danger"
                :loading="decomposeBusy"
                @click="doDecompose"
              >
                确认拆解
              </van-button>
            </div>
          </template>
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

.bc-warn {
  margin: 0;
  padding: var(--ziwi-gap-sm);
  border-radius: var(--ziwi-radius-sm);
  background: var(--ziwi-warning-bg, #fff7e6);
  color: var(--ziwi-warning-text, #8a5a00);
  font-size: var(--ziwi-font-size-sm);
  line-height: var(--ziwi-lineheight-normal);
}

.bc-warn code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
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

/* ── 返修拆解 ──────────────────────────────────────────────── */
.bc-decompose {
  margin-top: var(--ziwi-gap-md);
  padding-top: var(--ziwi-gap-md);
  border-top: 1px dashed var(--ziwi-line-2, #ebedf0);
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-sm);
}
.bc-decompose__warn {
  margin: 0;
  font-size: var(--ziwi-font-size-sm);
  line-height: 1.6;
  color: var(--ziwi-warning-text, #b26500);
  background: var(--ziwi-warning-bg, #fff7e6);
  border-radius: var(--ziwi-radius-sm, 4px);
  padding: 8px 10px;
  /* 长码串要能断行：定子/转子码连写时会把版面顶出去 */
  word-break: break-all;
}
.bc-decompose__done {
  margin: 0;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-success-text, #07c160);
}
.bc-decompose__actions {
  display: grid;
  /* 两个按钮等宽：确认拆解不该比取消更容易点中 */
  grid-template-columns: 1fr 1fr;
  gap: var(--ziwi-gap-sm);
}
/* 热区 44px：车间触摸屏靠拇指点，默认 32px 的按钮在手持机上是灾难 */
.bc-decompose :deep(.van-button) {
  min-height: 44px;
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
