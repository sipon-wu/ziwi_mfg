<script lang="ts">
/**
 * 一条待修正项。放在普通 `<script>` 块里导出：
 * `<script setup>` 不允许出现 ES 模块导出，而页面需要这个类型来组织 `items`。
 */
export interface ZiwiErrorItem {
  /** 字段名（与 `ZiwiSelect` / `van-field` 的 `data-field` 对应） */
  name: string
  /** 字段标签（给人看的名字） */
  label: string
  /** 具体问题（由 `txt.validation.*` 生成） */
  message: string
}
</script>

<script setup lang="ts">
/**
 * ZiwiErrorSummary — 顶部错误摘要（「N 项待修正」，可点跳）
 *
 * 为什么需要它：车间场景下"滚回去找"的成本极高（一屏只有一个字段），
 * 表单越短越不能靠 toast。UE §5.1「校验失败」要求四件事同时成立：
 * ① 顶部摘要 ② 自动滚动到第一个错误字段 ③ 字段高亮 + 就近原因（`ZiwiFieldError`）
 * ④ 焦点落入该字段。本组件负责 ①，并把 ② 的入口（点击某条 → 跳转）也做掉。
 *
 * 文案唯一来源：`txt.validation.summary(n)` → 「N 项待修正」。页面不得自己拼。
 *
 * 依据：UE §5.1「校验失败」、UE-10；架构 §2.6 追溯矩阵。
 */
import { computed } from 'vue'
import { txt } from '@/config/uiText'

interface Props {
  /** 待修正项清单；为空时不渲染 */
  items: ZiwiErrorItem[]
  /** 是否显示（页面通常传「已提交过一次」，避免一进页面就报红） */
  show?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  show: true,
})

const emit = defineEmits<{
  /** 点击某一条 → 页面滚到对应字段并聚焦 */
  jump: [name: string]
}>()

const visible = computed(() => props.show && props.items.length > 0)

/** 标题：N 项待修正（唯一真源） */
const summaryText = computed(() => txt.validation.summary(props.items.length))

/**
 * 行内问题文案。
 *
 * `txt.validation.*` 生成的是「字段 + 问题」（如「设备必填」），而摘要行左侧
 * 已经渲染了字段名，两者直接拼会读成「设备 设备必填」。因此这里把开头重复的
 * 字段名去掉，只剩「必填」。
 */
function displayMessage(item: ZiwiErrorItem): string {
  const message = item.message ?? ''
  if (item.label && message.startsWith(item.label)) {
    return message.slice(item.label.length).trim()
  }
  return message
}

function onJump(name: string): void {
  emit('jump', name)
}
</script>

<template>
  <section v-if="visible" class="ziwi-error-summary" role="alert" aria-live="assertive">
    <header class="ziwi-error-summary__head">
      <van-icon name="warning-o" class="ziwi-error-summary__icon" />
      <span class="ziwi-error-summary__title">{{ summaryText }}</span>
    </header>
    <ul class="ziwi-error-summary__list">
      <li
        v-for="item in items"
        :key="item.name"
        class="ziwi-error-summary__item"
        role="button"
        tabindex="0"
        @click="onJump(item.name)"
        @keydown.enter.prevent="onJump(item.name)"
        @keydown.space.prevent="onJump(item.name)"
      >
        <span class="ziwi-error-summary__label">{{ item.label }}</span>
        <span class="ziwi-error-summary__msg">{{ displayMessage(item) }}</span>
        <van-icon name="arrow" class="ziwi-error-summary__arrow" />
      </li>
    </ul>
  </section>
</template>

<style scoped>
.ziwi-error-summary {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  margin-bottom: var(--ziwi-gap-md);
  border: 1px solid var(--ziwi-state-danger-bd);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
  overflow: hidden;
}

.ziwi-error-summary__head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  font-size: var(--ziwi-font-size-lg);
  font-weight: 700;
}

.ziwi-error-summary__icon {
  font-size: var(--ziwi-font-size-xl);
}

.ziwi-error-summary__title {
  min-width: 0;
}

.ziwi-error-summary__list {
  margin: 0;
  padding: 0;
  list-style: none;
  background: var(--ziwi-bg-white);
  border-top: 1px solid var(--ziwi-state-danger-bd);
}

.ziwi-error-summary__item {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  /* 可点行必须达热区（UE-P0-02） */
  min-height: var(--ziwi-touch-min);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  font-size: var(--ziwi-font-size-md);
  line-height: var(--ziwi-lineheight-normal);
  border-bottom: 1px solid var(--ziwi-border-light);
  cursor: pointer;
}

.ziwi-error-summary__item:last-child {
  border-bottom: none;
}

.ziwi-error-summary__item:active {
  background: var(--ziwi-bg-light);
}

html[data-hover='on'] .ziwi-error-summary__item:hover {
  background: var(--ziwi-bg-light);
}

.ziwi-error-summary__label {
  flex: 0 0 auto;
  max-width: 40%;
  font-weight: 500;
  color: var(--ziwi-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ziwi-error-summary__msg {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--ziwi-state-danger-fg);
  overflow-wrap: anywhere;
}

.ziwi-error-summary__arrow {
  flex: none;
  color: var(--ziwi-text-muted);
}
</style>
