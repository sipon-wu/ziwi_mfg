<script setup lang="ts">
/**
 * ZiwiFormSheet — 表单浮层容器
 *
 * 唯一职责：把 UE §3.3 的 R1 / R2 / R3 / R4 四条容器级硬约束**在一处**实现，
 * 业务页不再自己组合 `van-dialog + van-picker + 内联 div 滚动条`。
 *
 * | 约束 | 本组件的落点 |
 * |---|---|
 * | **R1** 单一滚动容器 | `__body` 是唯一 `overflow-y:auto` 元素，且 `overscroll-behavior:contain`
 *  + 边界 `preventDefault`（滚动链不穿透到背景，UE-P0-03 的机械判据） |
 * | **R2** 宽度由策略定 | 宽度写在 `.ziwi-sheet-popup--{variant}` 上（100% 来自策略，不由内容撑开）；
 *  内容 `min-width:0` + `overflow-wrap:anywhere` |
 * | **R3** 只有一组确认 | 内层组件调 `registerOwnedConfirm(token)` → footer 立即让位 |
 * | **R4** 主操作常驻 | footer 是 sheet 内部的 `position:sticky;bottom:0`，**不是** `position:fixed`
 *  （fixed 会脱离 sheet 定位上下文，在 T 抽屉里横跨整屏） |
 *
 * 三种形态（W 居中 dialog / T 右侧抽屉 / H 全屏 page）**只有三个分支点**：
 * ① `van-popup position`；② `round` 与 safe-area；③ footer 是否 sticky 及高度策略。
 * DOM 结构、按钮、滚动策略、宽度策略完全一致 —— 「一份代码出三形态」靠的就是这个。
 *
 * 依据：架构 §2.1；UE §3.2「新建/编辑表单」行、§3.3 R1–R4、§6.3「误滑关闭」、UE-P0-03/04、UE-02/03/05。
 */
import { computed, nextTick, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useFormFactor } from '@/composables/useFormFactor'
import {
  ZIWI_SHEET_CTX,
  sheetVariantOf,
  type CloseReason,
  type SheetVariant,
  type ZiwiSheetContext,
} from './context'

interface Props {
  /** 显隐（`v-model:show`） */
  show: boolean
  /** 标题（左对齐主标题） */
  title: string
  /** 容器形态；`auto` 由 formFactor 派生（W→dialog / T→drawer / H→page） */
  variant?: 'auto' | SheetVariant
  /**
   * 宽度策略：
   * - `ratio`（默认）：视口比例 + 上限（R2 的标准解）
   * - `fixed`：按内容型固定档（仅确认类浮层使用，表单禁用）
   */
  widthPolicy?: 'ratio' | 'fixed'
  /** 有未保存内容 → 禁止遮罩关闭，且关闭请求转成 `close-blocked` */
  dirty?: boolean
  /** 提交中 → 全表锁定，按钮进入锁定态（UE-P0-05） */
  submitting?: boolean
  /** 主操作文案 */
  submitText?: string
  /** 次操作文案（空串表示不渲染次按钮） */
  cancelText?: string
  /** 强制隐藏 footer（内层声明 ownedConfirm 时自动置 true） */
  hideFooter?: boolean
  /** 是否显示 footer（默认 true） */
  showFooter?: boolean
  /** 是否允许点遮罩关闭；默认 false（§6.3 误滑关闭） */
  closeOnOverlay?: boolean
  /** 滚动策略：唯一合法值 `sheet-only`，保留字段防被绕开（R1） */
  scrollPolicy?: 'sheet-only'
  /** 关联表单 id，主按钮用 native submit 时透传 */
  formId?: string
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'auto',
  widthPolicy: 'ratio',
  dirty: false,
  submitting: false,
  submitText: '确认',
  cancelText: '取消',
  hideFooter: false,
  showFooter: true,
  closeOnOverlay: false,
  scrollPolicy: 'sheet-only',
  formId: '',
})

const emit = defineEmits<{
  'update:show': [boolean]
  submit: []
  cancel: []
  opened: []
  closed: []
  /** 页面据此向用户解释"为什么关不掉"（dirty / submitting / 手势被禁） */
  'close-blocked': [reason: CloseReason]
  /** 请求把容器滚到某选择器（校验失败定位入口，UE-10） */
  'scroll-to': [selector: string]
}>()

const { formFactor } = useFormFactor()

/* ------------------------------------------------------------------ *
 * 形态 → 容器（第一个分支点：van-popup position）
 * ------------------------------------------------------------------ */

/** `auto` 时由形态派生；显式传值则完全不看视口（确认类浮层可强制居中） */
const effectiveVariant = computed<SheetVariant>(() =>
  props.variant === 'auto' ? sheetVariantOf(formFactor.value) : props.variant,
)

const popupPosition = computed<'center' | 'right' | 'bottom'>(() => {
  if (effectiveVariant.value === 'dialog') return 'center'
  if (effectiveVariant.value === 'drawer') return 'right'
  return 'bottom'
})

/** 第二个分支点：圆角。居中浮层与侧抽屉有圆角，全屏页无圆角（避免出现"卡片悬浮感"） */
const isRound = computed(() => effectiveVariant.value !== 'page')

/** 全屏页无遮罩，因此也不存在"点遮罩关闭" */
const overlayCloses = computed(() => props.closeOnOverlay && effectiveVariant.value !== 'page')

const popupClass = computed(() => [
  'ziwi-sheet-popup',
  `ziwi-sheet-popup--${effectiveVariant.value}`,
  props.widthPolicy === 'fixed' ? 'ziwi-sheet-popup--fixed-width' : '',
])

/* ------------------------------------------------------------------ *
 * R3：内层确认声明 → footer 让位
 * ------------------------------------------------------------------ */

/** 内层组件注册的确认令牌集合（Set 便于多内层共存时准确还原） */
const ownedConfirmTokens = ref<Set<symbol>>(new Set())

const hasOwnedConfirm = computed(() => ownedConfirmTokens.value.size > 0)

/** footer 实际是否渲染：showFooter && !hideFooter && 无内层确认 */
const footerVisible = computed(
  () => props.showFooter && !props.hideFooter && !hasOwnedConfirm.value,
)

/**
 * 注册"本层已有一组确认"。
 * @param token 调用方持有的唯一令牌（同一 token 重复注册是幂等的）
 */
function registerOwnedConfirm(token: symbol): void {
  const next = new Set(ownedConfirmTokens.value)
  next.add(token)
  ownedConfirmTokens.value = next
}

/**
 * 注销"本层已有一组确认"。
 * @param token 注册时使用的同一令牌
 */
function unregisterOwnedConfirm(token: symbol): void {
  if (!ownedConfirmTokens.value.has(token)) return
  const next = new Set(ownedConfirmTokens.value)
  next.delete(token)
  ownedConfirmTokens.value = next
}

/* ------------------------------------------------------------------ *
 * 脏状态
 * ------------------------------------------------------------------ */

const innerDirty = ref(false)

/** 实际脏状态：props 与子组件写入取或（任一为 true 即脏） */
const isDirty = computed(() => props.dirty || innerDirty.value)

function markDirty(v: boolean): void {
  innerDirty.value = v
}

/* ------------------------------------------------------------------ *
 * 打开 / 关闭
 * ------------------------------------------------------------------ */

const attemptedClose = ref<CloseReason | null>(null)
/** "关不掉"提示的显示态（2.5s 自动淡出） */
const showBlockedHint = ref(false)
let blockedTimer: ReturnType<typeof setTimeout> | null = null

/** 有未保存内容时的提示文案（UE §6.3 误滑关闭） */
const DIRTY_HINT = '有未保存内容，请先保存或放弃'
/** 提交中时不允许关闭的解释文案（UE-P0-05） */
const SUBMITTING_HINT = '正在提交，请稍候'

const blockedHintText = computed(() => (props.submitting ? SUBMITTING_HINT : DIRTY_HINT))

function clearBlockedTimer(): void {
  if (blockedTimer !== null) {
    clearTimeout(blockedTimer)
    blockedTimer = null
  }
}

function flashBlockedHint(): void {
  showBlockedHint.value = true
  clearBlockedTimer()
  blockedTimer = setTimeout(() => {
    showBlockedHint.value = false
    blockedTimer = null
  }, 2500)
}

/**
 * 请求关闭。所有关闭路径（遮罩 / 关闭按钮 / 取消按钮 / Esc）都走这里，
 * 保证 dirty 与 submitting 的守卫只有一处实现。
 *
 * @param reason 关闭原因，随 `close-blocked` 透给页面
 */
function requestClose(reason: CloseReason = 'cancel'): void {
  if (props.submitting) {
    attemptedClose.value = reason
    flashBlockedHint()
    emit('close-blocked', reason)
    return
  }
  if (isDirty.value) {
    attemptedClose.value = reason
    flashBlockedHint()
    emit('close-blocked', reason)
    return
  }
  attemptedClose.value = null
  emit('update:show', false)
  emit('cancel')
}

/** 关闭按钮 / 取消按钮 */
function onCancelClick(): void {
  requestClose('cancel')
}

/** 点遮罩：默认策略下 Vant 不会自动关（close-on-click-overlay=false），这里统一走守卫 */
function onOverlayClick(): void {
  requestClose('overlay')
}

/** 主操作 */
function onSubmitClick(): void {
  if (props.submitting) return
  emit('submit')
}

/** Esc 关闭（W 形态唯一的键盘路径；H/T 上无用但无害） */
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (!props.show) return
  // 层级优先：内层浮层（选择器/确认/回执）开着时，Esc 只关内层（R3 的键盘侧对应）
  if (ownedConfirmTokens.value.size > 0) return
  event.stopPropagation()
  requestClose('esc')
}

/* ------------------------------------------------------------------ *
 * R1：单一滚动容器 + 滚动链拦截
 * ------------------------------------------------------------------ */

const bodyRef = ref<HTMLElement | null>(null)
/** 浮层内当前 scrollTop（调试与"是否已滚动"判断用） */
const innerScrollTop = ref(0)
/** 触摸起始 Y，用于判断触摸方向 */
let touchStartY = 0

function isAtTop(): boolean {
  const el = bodyRef.value
  if (!el) return true
  return el.scrollTop <= 0
}

function isAtBottom(): boolean {
  const el = bodyRef.value
  if (!el) return true
  return el.scrollTop + el.clientHeight >= el.scrollHeight - 1
}

function onBodyScroll(): void {
  innerScrollTop.value = bodyRef.value?.scrollTop ?? 0
}

/** 内容不需要滚动时一律不穿透；需要滚动时只在两端拦（UE-P0-03 的机械判据） */
function onWheel(event: WheelEvent): void {
  const el = bodyRef.value
  if (!el) return
  const canScroll = el.scrollHeight > el.clientHeight + 1
  if (!canScroll) {
    event.preventDefault()
    return
  }
  const goingUp = event.deltaY < 0
  const goingDown = event.deltaY > 0
  if ((goingUp && isAtTop()) || (goingDown && isAtBottom())) {
    event.preventDefault()
  }
}

function onTouchStart(event: TouchEvent): void {
  const touch = event.touches[0]
  touchStartY = touch ? touch.clientY : 0
}

function onTouchMove(event: TouchEvent): void {
  const el = bodyRef.value
  if (!el) return
  const canScroll = el.scrollHeight > el.clientHeight + 1
  if (!canScroll) {
    event.preventDefault()
    return
  }
  const touch = event.touches[0]
  if (!touch) return
  const delta = touch.clientY - touchStartY
  // 手指下滑（delta > 0）等价于内容上滚到顶
  if ((delta > 0 && isAtTop()) || (delta < 0 && isAtBottom())) {
    event.preventDefault()
  }
  touchStartY = touch.clientY
}

/** 把容器滚回顶部（分步表单切换步骤时用） */
function scrollToTop(): void {
  const el = bodyRef.value
  if (!el) return
  el.scrollTop = 0
  innerScrollTop.value = 0
}

/**
 * 把容器滚到指定选择器处并聚焦（UE-10「校验失败必须定位」）。
 *
 * 只滚**容器内部**，不动 `window` —— 因为 body 是唯一滚动容器（R1）。
 *
 * @param selector 容器内的 CSS 选择器（页面用 `[data-field="plan_name"]` 这类稳定属性）
 * @returns 是否找到目标元素
 */
function scrollToSelector(selector: string): boolean {
  const el = bodyRef.value
  if (!el) return false
  const target = el.querySelector<HTMLElement>(selector)
  if (!target) return false
  target.scrollIntoView({ block: 'center', behavior: 'smooth' })
  const focusable = target.matches('input, textarea, select, [tabindex]')
    ? target
    : target.querySelector<HTMLElement>('input, textarea, select, [tabindex]')
  // preventScroll：滚动作业已由 scrollIntoView 完成，避免焦点再跳一次
  focusable?.focus({ preventScroll: true })
  return true
}

/* ------------------------------------------------------------------ *
 * 生命周期与对外暴露
 * ------------------------------------------------------------------ */

function onOpened(): void {
  showBlockedHint.value = false
  attemptedClose.value = null
  scrollToTop()
  nextTick(() => {
    // 打开后把焦点交给容器内的第一个可输入元素（手套场景省一次点击）
    const el = bodyRef.value
    const focusable = el?.querySelector<HTMLElement>(
      'input:not([type="hidden"]):not([readonly]), textarea',
    )
    focusable?.focus({ preventScroll: true })
  })
  emit('opened')
}

function onClosed(): void {
  ownedConfirmTokens.value = new Set()
  innerDirty.value = false
  innerScrollTop.value = 0
  clearBlockedTimer()
  showBlockedHint.value = false
  emit('closed')
}

function onDocumentKeydown(event: KeyboardEvent): void {
  onKeydown(event)
}

watch(
  () => props.show,
  (open) => {
    if (typeof document === 'undefined') return
    if (open) {
      document.addEventListener('keydown', onDocumentKeydown)
    } else {
      document.removeEventListener('keydown', onDocumentKeydown)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (typeof document !== 'undefined') {
    document.removeEventListener('keydown', onDocumentKeydown)
  }
  clearBlockedTimer()
})

/* ------------------------------------------------------------------ *
 * provide：把容器上下文下发（R1/R3 的协商通道）
 * ------------------------------------------------------------------ */

const sheetContext: ZiwiSheetContext = {
  variant: effectiveVariant.value,
  formFactor,
  size: 'md',
  opened: computed(() => props.show),
  dirty: innerDirty,
  submitting: computed(() => props.submitting),
  requestClose,
  close: () => {
    emit('update:show', false)
  },
  onBeforeClose: () => () => {},
  scrollToTop,
  scrollToSelector,
  registerOwnedConfirm,
  unregisterOwnedConfirm,
  hasOwnedConfirm,
  markDirty,
}

provide(ZIWI_SHEET_CTX, sheetContext)

defineExpose({
  effectiveVariant,
  scrollToSelector,
  scrollToTop,
  requestClose,
  bodyRef,
  hasOwnedConfirm,
})
</script>

<template>
  <van-popup
    :show="show"
    :position="popupPosition"
    :round="isRound"
    :close-on-click-overlay="overlayCloses"
    :lock-scroll="true"
    :safe-area-inset-bottom="false"
    teleport="body"
    :class="popupClass"
    @update:show="(v: boolean) => emit('update:show', v)"
    @click-overlay="onOverlayClick"
    @opened="onOpened"
    @closed="onClosed"
  >
    <div class="ziwi-sheet" :class="`ziwi-sheet--${effectiveVariant}`">
      <!-- 头部：标题 + 次级操作。主操作禁止放这里（R4） -->
      <header class="ziwi-sheet__header">
        <h2 class="ziwi-sheet__title">{{ title }}</h2>
        <div class="ziwi-sheet__header-extra">
          <slot name="header" />
        </div>
        <button
          type="button"
          class="ziwi-sheet__close"
          aria-label="关闭"
          @click="onCancelClick"
        >
          <van-icon name="cross" size="18" />
        </button>
      </header>

      <!-- 关不掉时的解释（§6.3：必须告诉用户为什么，而不是"点了没反应"） -->
      <div v-if="showBlockedHint" class="ziwi-sheet__hint" role="alert">
        <van-icon name="info-o" />
        <span>{{ blockedHintText }}</span>
      </div>

      <!-- R1：唯一滚动容器（外层没有任何其他 overflow） -->
      <div
        ref="bodyRef"
        class="ziwi-sheet__body"
        @scroll.passive="onBodyScroll"
        @wheel="onWheel"
        @touchstart.passive="onTouchStart"
        @touchmove="onTouchMove"
      >
        <slot />
      </div>

      <!-- R4：footer 在 sheet 内部 sticky，不随内容滚出；不是 fixed -->
      <footer v-if="footerVisible" class="ziwi-sheet__footer">
        <slot name="footer-extra" />
        <div class="ziwi-sheet__actions">
          <van-button
            v-if="cancelText"
            class="ziwi-sheet__btn ziwi-sheet__btn--secondary"
            plain
            :disabled="submitting"
            @click="onCancelClick"
          >
            {{ cancelText }}
          </van-button>
          <van-button
            class="ziwi-sheet__btn ziwi-sheet__btn--primary"
            type="primary"
            :loading="submitting"
            :disabled="submitting"
            :native-type="formId ? 'submit' : 'button'"
            :form="formId || undefined"
            @click="onSubmitClick"
          >
            {{ submitting ? '提交中…' : submitText }}
          </van-button>
        </div>
      </footer>

      <!-- 完全替换按钮区：一旦使用，本组件不再渲染任何按钮（arch §2.1 slots.footer） -->
      <footer v-if="$slots.footer" class="ziwi-sheet__footer ziwi-sheet__footer--custom">
        <slot name="footer" />
      </footer>
    </div>
  </van-popup>
</template>

<style scoped>
/* ============================================================
   R2：浮层宽度策略 —— 本文件是这一条的唯一承载者
   ------------------------------------------------------------
   宽度写成具体策略（min(上限, 视口比例)），**不写 width: fit-content / inline-flex**，
   内容再宽也撑不开外层。选择器带双类（0,2,0）以压过 Vant 的
   `.van-popup--bottom{width:100%}` 等单类规则，与「index.css 被加载两次」解耦。
   ============================================================ */
.ziwi-sheet-popup.ziwi-sheet-popup--dialog {
  width: min(900px, 62vw);
  max-height: 80vh;
}

.ziwi-sheet-popup.ziwi-sheet-popup--drawer {
  width: min(720px, 92vw);
  height: 100%;
}

.ziwi-sheet-popup.ziwi-sheet-popup--page {
  width: 100%;
  height: 100%;
  max-height: 100%;
}

/* 固定档：确认类浮层用，不与内容耦合 */
.ziwi-sheet-popup.ziwi-sheet-popup--fixed-width {
  width: min(420px, 92vw);
}

.ziwi-sheet {
  /* 三个分支点之外的**共享结构**：一行都不按形态分叉 */
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-height: 0;
  min-width: 0;
  background: var(--ziwi-bg-white);
  color: var(--ziwi-text-primary);
  font-size: var(--ziwi-font-size-lg);
  overflow: hidden; /* 外层绝不滚动：滚动只发生在 __body（R1） */
}

.ziwi-sheet--dialog {
  max-height: 80vh;
  height: auto;
  border-radius: var(--ziwi-radius-xl);
}

.ziwi-sheet--drawer {
  height: 100%;
}

.ziwi-sheet--page {
  height: 100%;
  border-radius: 0;
}

/* ── 头部 ── */
.ziwi-sheet__header {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex: none;
  padding: var(--ziwi-gap-md) var(--ziwi-gap-lg);
  border-bottom: 1px solid var(--ziwi-border);
  min-height: var(--ziwi-actionbar-h);
  box-sizing: border-box;
}

.ziwi-sheet__title {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  line-height: var(--ziwi-lineheight-tight);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ziwi-sheet__header-extra {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex: 0 0 auto;
}

.ziwi-sheet__close {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* 关闭按钮热区走 --ziwi-close-hit：裸手 48 / 手套 56（UE §6.1） */
  min-width: var(--ziwi-close-hit);
  min-height: var(--ziwi-close-hit);
  margin-right: calc(-1 * var(--ziwi-gap-sm));
  padding: 0;
  border: none;
  background: transparent;
  color: var(--ziwi-text-muted);
  cursor: pointer;
  border-radius: var(--ziwi-radius-md);
}

/* 悬停只作增强（R5）：只在真有指针时出现 */
html[data-hover='on'] .ziwi-sheet__close:hover {
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-primary);
}

/* ── 阻断提示 ── */
.ziwi-sheet__hint {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-lg);
  background: var(--ziwi-state-warning-bg);
  color: var(--ziwi-state-warning-fg);
  border-bottom: 1px solid var(--ziwi-state-warning-bd);
  font-size: var(--ziwi-font-size-md);
}

/* ── R1：唯一滚动容器 ── */
.ziwi-sheet__body {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  touch-action: pan-y;
  -webkit-overflow-scrolling: touch;
  padding: var(--ziwi-gap-lg);
  box-sizing: border-box;
  /* R2 的最后一道保险：内层再宽也不许把外层撑开 */
  overflow-wrap: anywhere;
}

:global(html[data-form-factor='H']) .ziwi-sheet__body {
  padding: var(--ziwi-gap-md);
}

/* ── R4：footer 在 sheet 内部 sticky ── */
.ziwi-sheet__footer {
  flex: none;
  position: sticky;
  bottom: 0;
  z-index: var(--ziwi-z-sticky);
  background: var(--ziwi-bg-white);
  border-top: 1px solid var(--ziwi-border);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-lg);
  box-sizing: border-box;
}

.ziwi-sheet--page .ziwi-sheet__footer {
  padding-bottom: calc(var(--ziwi-gap-sm) + env(safe-area-inset-bottom, 0px));
}

.ziwi-sheet__footer--custom {
  padding: 0;
}

.ziwi-sheet__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  /* 不同语义按钮之间 24px，防误触（UE §6.3） */
  gap: var(--ziwi-touch-gap-sem);
}

.ziwi-sheet__btn {
  /* 热区由令牌保证：裸手 48 / 手套 56，不写死像素 */
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.ziwi-sheet__btn--primary {
  flex: 1 1 auto;
  max-width: 60%;
}

.ziwi-sheet__btn--secondary {
  flex: 0 0 auto;
  max-width: 40%;
}

/* H 形态：两按钮等分，主操作仍占更多宽度但都够大 */
:global(html[data-form-factor='H']) .ziwi-sheet__btn--primary {
  max-width: none;
  flex: 2 1 0;
}

:global(html[data-form-factor='H']) .ziwi-sheet__btn--secondary {
  max-width: none;
  flex: 1 1 0;
}
</style>
