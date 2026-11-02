<script setup lang="ts">
/**
 * ZiwiCodeText — 编码类文本（等宽 + 单行 + 中间省略 + 展开 + 复制）
 *
 * 车间里最常被念错、抄错的就是编码（`EQ-B1-11012316`、`WO-20261102-0012`）。
 * UE §4.2 给出的展示规则是：等宽、不换行、超长**中间省略保留首尾**、点击展开全文、一键复制。
 * 为什么保留首尾：现场对码常常靠"看头看尾"，尾部流水号才是区分项。
 *
 * 依据：UE §4.2、架构 §5.2。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { txt } from '@/config/uiText'

interface Props {
  /** 编码值（必填；空值显示占位符而不是空白，避免"以为没数据"） */
  code?: string | null
  /** 展示长度上限（超出则中间省略） */
  maxLength?: number
  /** 是否可复制 */
  copyable?: boolean
  /** 是否可点开展开全文 */
  expandable?: boolean
  /** 前缀标签（如「设备编码」） */
  label?: string
  /** 字号档 */
  size?: 'sm' | 'md' | 'lg'
}

const props = withDefaults(defineProps<Props>(), {
  code: '',
  maxLength: 20,
  copyable: true,
  expandable: true,
  label: '',
  size: 'md',
})

const emit = defineEmits<{
  copy: [code: string]
  expand: [expanded: boolean]
}>()

const expanded = ref(false)
const copied = ref(false)
const copyFallback = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

const rawCode = computed(() => (props.code === null || props.code === undefined ? '' : String(props.code)))

const isEmpty = computed(() => rawCode.value.trim().length === 0)

/**
 * 中间省略：`EQ-B1-1101…2316`。
 * 之所以在 JS 里截断而不是只用 CSS：CSS 的 `direction:rtl` 省略法在不同浏览器下
 * 对连字符位置的处理不一致，现场会出现"尾号被吃掉"的情况（对码直接失败）。
 */
const displayText = computed(() => {
  const code = rawCode.value
  if (expanded.value) return code
  const limit = Math.max(6, props.maxLength)
  if (code.length <= limit) return code
  const head = Math.ceil((limit - 1) / 2)
  const tail = Math.floor((limit - 1) / 2)
  return `${code.slice(0, head)}…${code.slice(code.length - tail)}`
})

const canExpand = computed(() => props.expandable && rawCode.value.length > Math.max(6, props.maxLength))

function toggleExpand(): void {
  if (!canExpand.value) return
  expanded.value = !expanded.value
  emit('expand', expanded.value)
}

async function onCopy(): Promise<void> {
  if (isEmpty.value) return
  emit('copy', rawCode.value)
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(rawCode.value)
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

onBeforeUnmount(() => {
  if (copiedTimer !== null) {
    clearTimeout(copiedTimer)
    copiedTimer = null
  }
})
</script>

<template>
  <span class="ziwi-code-text" :class="`ziwi-code-text--${size}`">
    <span v-if="label" class="ziwi-code-text__label">{{ label }}</span>
    <code
      class="ziwi-code-text__value"
      :class="{ 'ziwi-code-text__value--expandable': canExpand, 'ziwi-code-text__value--empty': isEmpty }"
      :title="rawCode"
      @click="toggleExpand"
    >
      {{ isEmpty ? '未设置' : displayText }}
    </code>
    <button
      v-if="canExpand"
      type="button"
      class="ziwi-code-text__action"
      :aria-label="expanded ? txt.action.collapse : txt.action.expand"
      @click.stop="toggleExpand"
    >
      {{ expanded ? txt.action.collapse : txt.action.expand }}
    </button>
    <button
      v-if="copyable && !isEmpty"
      type="button"
      class="ziwi-code-text__action"
      aria-label="复制"
      @click.stop="onCopy"
    >
      {{ copied ? '已复制' : '复制' }}
    </button>
    <input
      v-if="copyFallback"
      class="ziwi-code-text__fallback"
      :value="rawCode"
      readonly
      @focus="($event.target as HTMLInputElement).select()"
    />
  </span>
</template>

<style scoped>
.ziwi-code-text {
  display: inline-flex;
  align-items: center;
  gap: var(--ziwi-gap-xs);
  max-width: 100%;
  min-width: 0;
  flex-wrap: wrap;
}

.ziwi-code-text__label {
  flex: none;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-secondary);
}

.ziwi-code-text__value {
  min-width: 0;
  max-width: 100%;
  padding: 0 var(--ziwi-gap-2xs);
  border-radius: var(--ziwi-radius-sm);
  background: var(--ziwi-bg-light);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: 0.02em;
  color: var(--ziwi-text-primary);
  /* 单行不换行（§4.2）；省略由 JS 的中间省略负责，这里只兜底 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  overflow-wrap: normal;
}

.ziwi-code-text--sm .ziwi-code-text__value {
  font-size: var(--ziwi-font-size-sm);
}

.ziwi-code-text--md .ziwi-code-text__value {
  font-size: var(--ziwi-font-size-md);
}

.ziwi-code-text--lg .ziwi-code-text__value {
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
}

/* 展开态允许换行，把全文完整露出来 */
.ziwi-code-text__value--expandable {
  cursor: pointer;
}

.ziwi-code-text__value--empty {
  color: var(--ziwi-text-muted);
  background: transparent;
}

.ziwi-code-text__action {
  flex: none;
  min-height: var(--ziwi-touch-min);
  min-width: var(--ziwi-touch-min);
  padding: 0 var(--ziwi-gap-sm);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  background: var(--ziwi-bg-white);
  color: var(--ziwi-primary);
  font-size: var(--ziwi-font-size-sm);
  cursor: pointer;
}

.ziwi-code-text__fallback {
  width: 100%;
  margin-top: var(--ziwi-gap-xs);
  padding: var(--ziwi-gap-xs) var(--ziwi-gap-sm);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--ziwi-font-size-sm);
}
</style>
