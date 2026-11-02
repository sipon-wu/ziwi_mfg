<script lang="ts">
/**
 * 关键数量行。放在普通 `<script>` 块里导出（`<script setup>` 不允许 ES 模块导出）。
 */
export interface ZiwiReceiptQty {
  label: string
  value: number | string
  unit?: string
}
</script>

<script setup lang="ts">
/**
 * ZiwiReceipt — 回执卡（UE §5.1「保存成功」、§2.5「三秒可判」、§5.3 载体表、UE-11）
 *
 * ## 为什么不能用 toast 顶替
 * toast 只回答"成功了吗"，回答不了"成功了什么、下一步去哪"；而车间用户常把回执
 * **拍照留档**，所以必须同时给出：单号（可复制）+ 关键数量 + 时间 + 下一状态。
 *
 * ## 硬规则
 * 1. `docNo` 为空时**不渲染**并 `console.error`（UE-11 是 P1 红线判据）；
 * 2. 必须由调用方在成功后**显式**打开，禁止用 toast 替代；
 * 3. 两个动作固定是「继续新建」与「查看单据」，不出现第三个主操作；
 * 4. 返回列表后该行高亮 + 滚到可见：由页面自身记录 `lastCreatedId` 完成（不抽公共件）。
 *
 * 依据：架构 §2.3、§5.1；UE-11。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { formatQty, txt } from '@/config/uiText'
import type { StateSemantic } from '@/config/statusDict'

interface Props {
  show: boolean
  /** 标题，默认「保存成功」 */
  title?: string
  /** 单号（必填；为空则不渲染） */
  docNo: string
  /** 单号标签，如「报工单号」「出库单号」 */
  docNoLabel?: string
  /** 关键数量，1–3 项 */
  quantities?: ZiwiReceiptQty[]
  /** 已完成格式化的时间（HH:mm 或 MM-DD HH:mm） */
  time: string
  /** 下一状态（含颜色 + 文字双编码） */
  nextState?: { label: string; semantic: StateSemantic }
  /** 主操作：继续新建 / 查看单据 */
  primaryAction?: { text: string; kind: 'continue' | 'view' }
  /** 次操作 */
  secondaryAction?: { text: string }
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  docNoLabel: '单号',
  quantities: () => [],
  time: '',
  nextState: undefined,
  primaryAction: undefined,
  secondaryAction: undefined,
})

const emit = defineEmits<{
  'update:show': [boolean]
  primary: []
  secondary: []
  closed: []
}>()

/** 语义档 → 图标（双编码的"形状"一半，与 statusDict 的口径一致） */
const SEMANTIC_ICON: Record<StateSemantic, string> = {
  neutral: 'info-o',
  progress: 'clock-o',
  success: 'passed',
  warning: 'warning-o',
  danger: 'close',
}

const titleText = computed(() => props.title || txt.receipt.title('保存'))

/** 单号是否合规（纯计算，无副作用） */
const hasDocNo = computed(
  () => typeof props.docNo === 'string' && props.docNo.trim().length > 0,
)

/** 单号为空即违规：既不渲染，也要让开发期可见（UE-11 红线） */
const canRender = hasDocNo

const visible = computed(() => props.show && hasDocNo.value)

// 副作用（告警）放到 watch 里，避免 computed 每次求值都刷一条日志
watch(
  () => props.show,
  (open) => {
    if (open && !hasDocNo.value) {
      // eslint-disable-next-line no-console
      console.error('[ZiwiReceipt] docNo 为空：回执卡必须带单号（UE-11 红线），本次不渲染')
    }
  },
  { immediate: true },
)

/** 数量行：最多 3 项（超出会让回执卡在 H 形态一屏放不下） */
const qtyRows = computed(() => props.quantities.slice(0, 3))

const nextIcon = computed(() =>
  props.nextState ? SEMANTIC_ICON[props.nextState.semantic] : 'info-o',
)

/* ------------------------------------------------------------------ *
 * 复制单号
 * ------------------------------------------------------------------ */

const copied = ref(false)
/** http 环境没有 navigator.clipboard 时显示可选中文本框（降级不失败） */
const copyFallback = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

async function onCopy(): Promise<void> {
  if (!canRender.value) return
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(props.docNo)
      copied.value = true
      copyFallback.value = false
    } else {
      copyFallback.value = true
    }
  } catch {
    copyFallback.value = true
  }
  if (copiedTimer !== null) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copied.value = false
    copiedTimer = null
  }, 2000)
}

function onPrimary(): void {
  emit('primary')
}

function onSecondary(): void {
  emit('secondary')
}

function close(): void {
  emit('update:show', false)
  emit('closed')
}

onBeforeUnmount(() => {
  if (copiedTimer !== null) {
    clearTimeout(copiedTimer)
    copiedTimer = null
  }
})
</script>

<template>
  <van-popup
    :show="visible"
    position="bottom"
    round
    teleport="body"
    :lock-scroll="true"
    :close-on-click-overlay="false"
    class="ziwi-receipt__popup"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div class="ziwi-receipt">
      <header class="ziwi-receipt__header">
        <van-icon name="passed" class="ziwi-receipt__ok" />
        <h2 class="ziwi-receipt__title">{{ titleText }}</h2>
        <button type="button" class="ziwi-receipt__close" aria-label="关闭" @click="close">
          <van-icon name="cross" size="18" />
        </button>
      </header>

      <div class="ziwi-receipt__body">
        <!-- 单号：等宽 + 可复制 + 长串中间省略（§4.2） -->
        <div class="ziwi-receipt__docno">
          <span class="ziwi-receipt__docno-label">{{ docNoLabel }}</span>
          <code class="ziwi-receipt__docno-value" :title="docNo">{{ docNo }}</code>
          <van-button size="small" plain type="primary" @click="onCopy">
            {{ copied ? '已复制' : '复制' }}
          </van-button>
        </div>
        <input
          v-if="copyFallback"
          class="ziwi-receipt__copy-fallback"
          :value="docNo"
          readonly
          @focus="($event.target as HTMLInputElement).select()"
        />

        <!-- 关键数量（1–3 项） -->
        <dl v-if="qtyRows.length" class="ziwi-receipt__qtys">
          <div v-for="row in qtyRows" :key="row.label" class="ziwi-receipt__qty">
            <dt class="ziwi-receipt__qty-label">{{ row.label }}</dt>
            <dd class="ziwi-receipt__qty-value">
              {{ formatQty(row.value) }}
              <span v-if="row.unit" class="ziwi-receipt__qty-unit">{{ row.unit }}</span>
            </dd>
          </div>
        </dl>

        <!-- 时间 -->
        <p v-if="time" class="ziwi-receipt__time">{{ txt.receipt.time(time) }}</p>

        <!-- 下一状态：颜色 + 文字 + 图标三重编码 -->
        <p v-if="nextState" class="ziwi-receipt__next">
          <span>下一状态</span>
          <span class="ziwi-state" :class="`ziwi-state--${nextState.semantic}`">
            <van-icon :name="nextIcon" />
            {{ nextState.label }}
          </span>
        </p>

        <!-- 差异摘要 / 被影响对象 / NCR 单号等 -->
        <div v-if="$slots.extra" class="ziwi-receipt__extra">
          <slot name="extra" />
        </div>
      </div>

      <footer class="ziwi-receipt__footer">
        <van-button
          v-if="secondaryAction"
          class="ziwi-receipt__btn"
          plain
          @click="onSecondary"
        >
          {{ secondaryAction.text }}
        </van-button>
        <van-button
          v-if="primaryAction"
          class="ziwi-receipt__btn ziwi-receipt__btn--primary"
          type="primary"
          @click="onPrimary"
        >
          {{ primaryAction.text }}
        </van-button>
      </footer>
    </div>
  </van-popup>
</template>

<style scoped>
.ziwi-receipt__popup {
  width: 100%;
  border-radius: var(--ziwi-radius-xl) var(--ziwi-radius-xl) 0 0;
  overflow: hidden;
}

.ziwi-receipt {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  max-height: 85vh;
  background: var(--ziwi-bg-white);
}

.ziwi-receipt__header {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex: none;
  padding: var(--ziwi-gap-lg) var(--ziwi-gap-lg) var(--ziwi-gap-sm);
}

.ziwi-receipt__ok {
  flex: none;
  font-size: var(--ziwi-font-size-2xl);
  color: var(--ziwi-state-success-fg);
}

.ziwi-receipt__title {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
}

.ziwi-receipt__close {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: var(--ziwi-close-hit);
  min-height: var(--ziwi-close-hit);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--ziwi-text-muted);
  cursor: pointer;
  border-radius: var(--ziwi-radius-md);
}

.ziwi-receipt__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 var(--ziwi-gap-lg) var(--ziwi-gap-md);
}

.ziwi-receipt__docno {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex-wrap: wrap;
  padding: var(--ziwi-gap-md);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-bg-light);
  border: 1px solid var(--ziwi-border-light);
}

.ziwi-receipt__docno-label {
  flex: none;
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

.ziwi-receipt__docno-value {
  flex: 1 1 auto;
  /* R2：长单号不撑开浮层，中间省略保留尾段（§4.2） */
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl;
  text-align: left;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
}

.ziwi-receipt__copy-fallback {
  width: 100%;
  margin-top: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-sm);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  font-size: var(--ziwi-font-size-md);
}

.ziwi-receipt__qtys {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ziwi-gap-lg);
  margin: var(--ziwi-gap-md) 0 0;
  padding: 0;
}

.ziwi-receipt__qty {
  min-width: 0;
  flex: 1 1 33%;
}

.ziwi-receipt__qty-label {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.ziwi-receipt__qty-value {
  margin: var(--ziwi-gap-2xs) 0 0;
  font-size: var(--ziwi-font-size-2xl);
  font-weight: 700;
  line-height: var(--ziwi-lineheight-tight);
  color: var(--ziwi-text-primary);
}

.ziwi-receipt__qty-unit {
  font-size: var(--ziwi-font-size-sm);
  font-weight: 400;
  color: var(--ziwi-text-muted);
  margin-left: var(--ziwi-gap-2xs);
}

.ziwi-receipt__time {
  margin: var(--ziwi-gap-md) 0 0;
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

.ziwi-receipt__next {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  margin: var(--ziwi-gap-sm) 0 0;
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

.ziwi-receipt__extra {
  margin-top: var(--ziwi-gap-md);
}

.ziwi-receipt__footer {
  display: flex;
  align-items: center;
  gap: var(--ziwi-touch-gap-sem);
  flex: none;
  padding: var(--ziwi-gap-md) var(--ziwi-gap-lg);
  padding-bottom: calc(var(--ziwi-gap-md) + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid var(--ziwi-border);
}

.ziwi-receipt__btn {
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.ziwi-receipt__btn--primary {
  flex: 1 1 auto;
}
</style>
