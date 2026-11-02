<script setup lang="ts">
/**
 * ZiwiActionBar — 底部主操作条
 *
 * 职责（只做一件事）：把「主操作」常驻在拇指可达区。
 *
 * 依据：
 * - UE §3.3 **R4** 主操作必须常驻拇指可达区（H/T 形态固定底部），不随内容滚出
 * - UE-03 未滚动时主操作 `top < innerHeight`，或为 `position: fixed` 底部条
 * - UE §8「操作按钮位置」：表单页主操作固定底部（H/T）/ 浮层右下（W）
 *
 * 形态行为：
 * | 形态 | 行为 |
 * |---|---|
 * | H | 固定底部，单行两按钮（次要 + 主要），高度 `--ziwi-actionbar-h` |
 * | T | 固定底部，同 H |
 * | W | 不固定，随容器流式排在右下（表单底部），避免遮住宽屏内容 |
 *
 * 硬规则：
 * - 破坏性操作**永不**出现在主操作区（UE §8）
 * - 主按钮热区 ≥ `--ziwi-touch-min`（裸手 48 / 手套 56），由令牌保证
 * - 提交中按钮进入锁定态（配合 useSubmitLock，UE-P0-05）
 * - 只有一个语义组按钮（R3）：本组件自身不再输出"取消/确认"以外的第二组
 */
import { computed, provide, readonly, toRef } from 'vue'
import { useFormFactor } from '@/composables/useFormFactor'
import { actionBarIsFixed, ZIWI_ACTION_BAR_CTX } from './context'

interface Props {
  /** 主按钮文案 */
  primaryText?: string
  /** 次按钮文案，留空则不渲染次按钮 */
  secondaryText?: string
  /** 主按钮是否处于提交中（锁定态） */
  submitting?: boolean
  /** 主按钮是否禁用 */
  primaryDisabled?: boolean
  /** 次按钮是否禁用 */
  secondaryDisabled?: boolean
  /** 主按钮语义：danger 只允许用于「确认作废」这类已进入确认流程的动作 */
  primaryType?: 'primary' | 'danger' | 'success'
  /** 是否显示 safe-area 留白（iPhone / 全面屏手持机） */
  safeArea?: boolean
  /** 额外类名 */
  customClass?: string
}

const props = withDefaults(defineProps<Props>(), {
  primaryText: '提交',
  secondaryText: '',
  submitting: false,
  primaryDisabled: false,
  secondaryDisabled: false,
  primaryType: 'primary',
  safeArea: true,
  customClass: '',
})

const emit = defineEmits<{
  /** 主操作 */
  (e: 'primary'): void
  /** 次操作 */
  (e: 'secondary'): void
}>()

const { formFactor } = useFormFactor()

/** H/T 固定底部；W 走流式右下 */
const isFixed = computed(() => actionBarIsFixed(formFactor.value))

/** 操作条高度（含 safe-area），供页面让位 */
const height = computed(() => {
  const base = 'var(--ziwi-actionbar-h)'
  return props.safeArea
    ? `calc(${base} + env(safe-area-inset-bottom, 0px))`
    : base
})

/** 主按钮是否可点 */
const primaryClickable = computed(() => !props.submitting && !props.primaryDisabled)
const secondaryClickable = computed(() => !props.submitting && !props.secondaryDisabled)

/** 主按钮实际文案：提交中必须给出"在做什么"，不能只是转圈 */
const primaryLabel = computed(() => (props.submitting ? '提交中…' : props.primaryText))

const rootClass = computed(() => [
  'ziwi-actionbar',
  isFixed.value ? 'ziwi-actionbar--fixed' : 'ziwi-actionbar--inline',
  props.customClass,
])

function onPrimary(): void {
  if (!primaryClickable.value) return
  emit('primary')
}

function onSecondary(): void {
  if (!secondaryClickable.value) return
  emit('secondary')
}

// 向子组件暴露上下文：让页面内的字段知道自己要为底部条留出多少空间
provide(ZIWI_ACTION_BAR_CTX, {
  height,
  isFixed,
  submitting: readonly(toRef(props, 'submitting')),
})

defineExpose({ height, isFixed })
</script>

<template>
  <div :class="rootClass" :style="{ '--ziwi-actionbar-height': height }" role="toolbar">
    <div class="ziwi-actionbar__inner">
      <van-button
        v-if="secondaryText"
        class="ziwi-actionbar__btn ziwi-actionbar__btn--secondary"
        plain
        :disabled="!secondaryClickable"
        @click="onSecondary"
      >
        {{ secondaryText }}
      </van-button>
      <van-button
        class="ziwi-actionbar__btn ziwi-actionbar__btn--primary"
        :type="primaryType"
        :loading="submitting"
        :disabled="!primaryClickable"
        @click="onPrimary"
      >
        {{ primaryLabel }}
      </van-button>
    </div>
  </div>
</template>

<style scoped>
.ziwi-actionbar {
  box-sizing: border-box;
  background: var(--ziwi-bg-white);
  border-top: 1px solid var(--ziwi-border);
}

/* H/T：固定底部、拇指可达区 */
.ziwi-actionbar--fixed {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: var(--ziwi-z-actionbar);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-lg);
  padding-bottom: calc(var(--ziwi-gap-sm) + env(safe-area-inset-bottom, 0px));
  min-height: var(--ziwi-actionbar-height);
}

/* W：不固定，随表单流式排在右下（避免遮住宽屏内容） */
.ziwi-actionbar--inline {
  position: static;
  width: 100%;
  border-top: none;
  padding: var(--ziwi-gap-md) 0 0;
}

.ziwi-actionbar__inner {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--ziwi-touch-gap-sem); /* 不同语义按钮之间 24px，防误触（UE §6.1） */
}

/* 主按钮热区与字号由 vant-overrides.css 的 --van-button-default-height 保证，
   这里只兜底一次，防止后续有人把 Vant 变量改回去 */
.ziwi-actionbar__btn {
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.ziwi-actionbar__btn--primary {
  flex: 1 1 auto;
  max-width: 60%;
}
.ziwi-actionbar__btn--secondary {
  flex: 0 0 auto;
  max-width: 40%;
}

/* H 形态：两按钮等分，主操作占更多宽度但都够大 */
:global(html[data-form-factor='H']) .ziwi-actionbar--fixed {
  padding-left: var(--ziwi-gap-sm);
  padding-right: var(--ziwi-gap-sm);
}
:global(html[data-form-factor='H']) .ziwi-actionbar__btn--primary {
  max-width: none;
  flex: 2 1 0;
}
:global(html[data-form-factor='H']) .ziwi-actionbar__btn--secondary {
  max-width: none;
  flex: 1 1 0;
}
</style>
