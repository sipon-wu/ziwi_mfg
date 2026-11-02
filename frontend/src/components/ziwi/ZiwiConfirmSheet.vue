<script setup lang="ts">
/**
 * ZiwiConfirmSheet — 危险操作二次确认（架构 §5.2；UE §5.1「危险操作」、§6.2 长按、UE-13）
 *
 * ## 两档确认方式
 * | 风险 | 确认方式 | 理由 |
 * |---|---|---|
 * | 中风险（medium） | 明确的动作按钮（文案必须有语义，如「确认作废」） | 一致性优先 |
 * | 高风险（high） | 长按至进度环闭合（hold，默认）**或** 输入单据号后 4 位（type） | 不可撤销的操作需要"刻意成本" |
 *
 * ## 硬规则
 * 1. **重述后果与影响对象**：`objectLabel` + `consequence` 必须都渲染，缺一即违规（UE-13）；
 * 2. 取消按钮文案是「再想想」而不是「取消」（UE §5.1 明确禁止无语义文案）；
 * 3. 取消是默认焦点，且与主操作**不同位置**（防误触，§6.3）；
 * 4. 高风险长按：松手即取消、有进度反馈、**不得**用滑动删除之类禁止手势替代（§6.2）。
 *
 * 形态：W 居中浮层 / T、H 底部浮层（H 近全屏），与 §3.2「危险确认」行一致。
 */
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useFormFactor } from '@/composables/useFormFactor'
import { txt } from '@/config/uiText'
import { ZIWI_SHEET_CTX } from './context'

/** 风险档 */
type Risk = 'medium' | 'high'
/** 高风险确认方式 */
type HighMode = 'hold' | 'type'

interface Props {
  show: boolean
  /** 标题：动作语义，如「作废出库单」 */
  title: string
  /** 被影响对象标识（单据号 / 名称），**必填**（UE-13 断言它存在） */
  objectLabel: string
  /** 后果说明，如「作废后不可恢复，当前在制 30 件将回退」 */
  consequence?: string
  /** 风险档 */
  risk?: Risk
  /** 高风险确认方式 */
  highMode?: HighMode
  /** 高风险-输入模式：需要用户手输的原文（组件自动取尾部 N 位比对） */
  confirmCode?: string
  /** 高风险-长按模式：按住时长（ms） */
  holdMs?: number
  /** 主按钮动作词（中风险用），如「作废」→ 按钮文案「确认作废」 */
  action?: string
  /** 覆盖主按钮完整文案 */
  okText?: string
  /** 提交中（锁定） */
  submitting?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  consequence: '',
  risk: 'medium',
  highMode: 'hold',
  confirmCode: '',
  holdMs: 1500,
  action: '执行',
  okText: '',
  submitting: false,
})

const emit = defineEmits<{
  'update:show': [boolean]
  confirm: []
  cancel: []
  closed: []
}>()

const { formFactor } = useFormFactor()

/* ------------------------------------------------------------------ *
 * 形态
 * ------------------------------------------------------------------ */

const popupPosition = computed<'center' | 'bottom'>(() =>
  formFactor.value === 'W' ? 'center' : 'bottom',
)

const popupClass = computed(() => [
  'ziwi-confirm__popup',
  `ziwi-confirm__popup--${formFactor.value === 'W' ? 'dialog' : 'sheet'}`,
  formFactor.value === 'H' ? 'ziwi-confirm__popup--full' : '',
])

/* ------------------------------------------------------------------ *
 * 文案（全部来自 uiText，组件不拼字符串）
 * ------------------------------------------------------------------ */

const cancelText = computed(() => txt.danger.cancelLabel())
const okTextResolved = computed(() => props.okText || txt.danger.okLabel(props.action))
const holdHint = computed(() => txt.danger.holdHint(props.holdMs))
/** 高风险-输入模式：提示"后 N 位" */
const tailLength = 4
const typeHint = computed(() => txt.danger.typeHint(tailLength))

/* ------------------------------------------------------------------ *
 * R3：本层自带确认 → 外层 Sheet footer 让位
 * ------------------------------------------------------------------ */

const OWNED_CONFIRM_TOKEN: symbol = Symbol('ZiwiConfirmSheet')
const sheetContext = inject(ZIWI_SHEET_CTX, null)

/* ------------------------------------------------------------------ *
 * 高风险-长按进度环
 * ------------------------------------------------------------------ */

/** 0–1 的按住进度 */
const holdProgress = ref(0)
let rafId = 0
let holdStartAt = 0

function stopHold(): void {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = 0
  }
  holdProgress.value = 0
}

function tick(): void {
  if (!holdStartAt) return
  const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
  const ratio = Math.min(1, (now - holdStartAt) / Math.max(1, props.holdMs))
  holdProgress.value = ratio
  if (ratio >= 1) {
    rafId = 0
    holdStartAt = 0
    onConfirm()
    return
  }
  rafId = requestAnimationFrame(tick)
}

function startHold(): void {
  if (props.submitting || props.highMode !== 'hold') return
  stopHold()
  holdStartAt = typeof performance !== 'undefined' ? performance.now() : Date.now()
  rafId = requestAnimationFrame(tick)
}

/* ------------------------------------------------------------------ *
 * 高风险-输入尾号
 * ------------------------------------------------------------------ */

const typedCode = ref('')

const typeMatched = computed(() => {
  if (!props.confirmCode) return false
  const expected = props.confirmCode.slice(-tailLength)
  return typedCode.value.trim() === expected
})

/* ------------------------------------------------------------------ *
 * 提交
 * ------------------------------------------------------------------ */

/** 主操作是否可用 */
const canConfirm = computed(() => {
  if (props.submitting) return false
  if (props.risk === 'high' && props.highMode === 'type') return typeMatched.value
  return true
})

function onConfirm(): void {
  if (!canConfirm.value) return
  stopHold()
  emit('confirm')
}

function onCancel(): void {
  stopHold()
  emit('cancel')
  emit('update:show', false)
}

/** 关闭后复位所有瞬时状态（进度环 / 已输入尾号） */
function resetState(): void {
  stopHold()
  holdStartAt = 0
  typedCode.value = ''
}

watch(
  () => props.show,
  (open) => {
    if (!open) {
      resetState()
      if (sheetContext) sheetContext.unregisterOwnedConfirm(OWNED_CONFIRM_TOKEN)
      emit('closed')
    } else if (sheetContext) {
      sheetContext.registerOwnedConfirm(OWNED_CONFIRM_TOKEN)
    }
  },
)

onBeforeUnmount(() => {
  stopHold()
  sheetContext?.unregisterOwnedConfirm(OWNED_CONFIRM_TOKEN)
})

/** 进度环的 CSS 变量（动态值只能走绑定，不写死 style 字符串） */
const ringStyle = computed(() => ({
  '--ziwi-confirm-progress': `${Math.round(holdProgress.value * 360)}deg`,
}))

function onTypedInput(value: string): void {
  typedCode.value = value ?? ''
}
</script>

<template>
  <van-popup
    :show="show"
    :position="popupPosition"
    round
    teleport="body"
    :lock-scroll="true"
    :close-on-click-overlay="false"
    :class="popupClass"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div class="ziwi-confirm">
      <header class="ziwi-confirm__header">
        <van-icon name="warning-o" class="ziwi-confirm__icon" />
        <h2 class="ziwi-confirm__title">{{ title }}</h2>
      </header>

      <div class="ziwi-confirm__body">
        <!-- 重述影响对象与后果：UE-13 的机械判据就是这两段文本都存在 -->
        <p class="ziwi-confirm__object">{{ objectLabel }}</p>
        <p v-if="consequence" class="ziwi-confirm__consequence">{{ consequence }}</p>

        <!-- 高风险 A：长按进度环 -->
        <div v-if="risk === 'high' && highMode === 'hold'" class="ziwi-confirm__hold">
          <p class="ziwi-confirm__hint">{{ holdHint }}</p>
          <button
            type="button"
            class="ziwi-confirm__ring"
            :style="ringStyle"
            :aria-label="holdHint"
            @pointerdown.prevent="startHold"
            @pointerup="stopHold"
            @pointerleave="stopHold"
            @pointercancel="stopHold"
          >
            <span class="ziwi-confirm__ring-inner">
              {{ holdProgress >= 1 ? '已确认' : okTextResolved }}
            </span>
          </button>
        </div>

        <!-- 高风险 B：输入单据号后 N 位 -->
        <div v-else-if="risk === 'high' && highMode === 'type'" class="ziwi-confirm__type">
          <p class="ziwi-confirm__hint">{{ typeHint }}</p>
          <van-field
            :model-value="typedCode"
            class="ziwi-confirm__type-field"
            placeholder="输入后 4 位"
            inputmode="numeric"
            @update:model-value="onTypedInput"
          />
        </div>
      </div>

      <footer class="ziwi-confirm__footer">
        <!-- 取消在左（默认焦点），主操作在右：不同位置 + 语义文案（§6.3） -->
        <van-button
          class="ziwi-confirm__btn ziwi-confirm__btn--cancel"
          plain
          autofocus
          @click="onCancel"
        >
          {{ cancelText }}
        </van-button>
        <van-button
          v-if="risk === 'medium' || highMode === 'type'"
          class="ziwi-confirm__btn ziwi-confirm__btn--ok"
          type="danger"
          :disabled="!canConfirm"
          :loading="submitting"
          @click="onConfirm"
        >
          {{ okTextResolved }}
        </van-button>
      </footer>
    </div>
  </van-popup>
</template>

<style scoped>
/* 形态分支：只有容器宽度与高度策略不同（§3.2 危险确认行） */
.ziwi-confirm__popup--dialog {
  width: min(520px, 92vw);
}

.ziwi-confirm__popup--sheet {
  width: 100%;
}

.ziwi-confirm__popup--full {
  width: 100%;
  height: 100%;
}

.ziwi-confirm__popup--full .ziwi-confirm {
  height: 100%;
}

.ziwi-confirm {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  background: var(--ziwi-bg-white);
}

.ziwi-confirm__header {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex: none;
  padding: var(--ziwi-gap-lg) var(--ziwi-gap-lg) var(--ziwi-gap-sm);
}

.ziwi-confirm__icon {
  flex: none;
  font-size: var(--ziwi-font-size-2xl);
  color: var(--ziwi-state-danger-fg);
}

.ziwi-confirm__title {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  line-height: var(--ziwi-lineheight-tight);
  color: var(--ziwi-text-primary);
  overflow-wrap: anywhere;
}

.ziwi-confirm__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 var(--ziwi-gap-lg) var(--ziwi-gap-md);
}

.ziwi-confirm__object {
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-text-primary);
  overflow-wrap: anywhere;
}

.ziwi-confirm__consequence {
  margin: var(--ziwi-gap-sm) 0 0;
  font-size: var(--ziwi-font-size-lg);
  line-height: var(--ziwi-lineheight-loose);
  color: var(--ziwi-state-danger-fg);
  overflow-wrap: anywhere;
}

.ziwi-confirm__hint {
  margin: var(--ziwi-gap-lg) 0 var(--ziwi-gap-sm);
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

/* 进度环：conic-gradient 的进度角由 --ziwi-confirm-progress 驱动 */
.ziwi-confirm__ring {
  --ziwi-confirm-progress: 0deg;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: calc(var(--ziwi-touch-danger) * 3);
  height: calc(var(--ziwi-touch-danger) * 3);
  max-width: 100%;
  padding: 0;
  border: none;
  border-radius: var(--ziwi-radius-round);
  background: conic-gradient(
    var(--ziwi-state-danger-fg) var(--ziwi-confirm-progress),
    var(--ziwi-border) 0
  );
  cursor: pointer;
  touch-action: none; /* 长按期间禁止滚动（§6.2 长按只允许这一种用途） */
  user-select: none;
}

.ziwi-confirm__ring-inner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: calc(100% - var(--ziwi-gap-md) * 2);
  height: calc(100% - var(--ziwi-gap-md) * 2);
  border-radius: var(--ziwi-radius-round);
  background: var(--ziwi-bg-white);
  font-size: var(--ziwi-font-size-lg);
  font-weight: 700;
  color: var(--ziwi-state-danger-fg);
  text-align: center;
  padding: var(--ziwi-gap-sm);
  box-sizing: border-box;
}

.ziwi-confirm__type-field {
  /* 输入框热区走令牌（UE-08） */
  min-height: var(--ziwi-touch-min);
}

.ziwi-confirm__footer {
  display: flex;
  align-items: center;
  gap: var(--ziwi-touch-gap-sem);
  flex: none;
  padding: var(--ziwi-gap-md) var(--ziwi-gap-lg);
  padding-bottom: calc(var(--ziwi-gap-md) + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid var(--ziwi-border);
}

.ziwi-confirm__btn {
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.ziwi-confirm__btn--cancel {
  flex: 0 0 auto;
  max-width: 40%;
  color: var(--ziwi-text-primary);
}

.ziwi-confirm__btn--ok {
  flex: 1 1 auto;
}
</style>
