<script lang="ts">
/**
 * 面板形态。`sheet` = 底部浮层（T/H 档，带标题栏与关闭键）；
 * `dropdown` = 锚定下拉（W 档，无标题栏，锚在字段下方）。
 */
export type ZiwiPanelVariant = 'sheet' | 'dropdown'
</script>

<script setup lang="ts">
/**
 * ZiwiSelectPanel — 枚举选择器的**内容面板**（`ZiwiSelect` 的内部件）
 *
 * ## 为什么单独拆出来
 * 同一个面板要装在两种完全不同的容器里：
 * - **T/H 档**：`van-popup position="bottom"` 底部浮层 —— 是模态的，需要有标题栏
 *   告诉用户"你在选什么"，也需要关闭键；
 * - **W 档**：锚定在字段下方的小下拉 —— 是非模态的，字段的 label 就在上方可见，
 *   再加一个标题栏反而是冗余（这也是桌面端下拉的通行形态）。
 *
 * 容器不同但内容（搜索框 + 选项列表）完全相同。不拆的话这段 40 行模板要在
 * `ZiwiSelect` 里写两遍，任何一处改文案/空态都得改两遍 —— 早晚漂。
 *
 * ## 它不认识"形态"
 * 只认 `variant`。形态判定留在 `ZiwiSelect`，这里不做任何 `matchMedia` 判断，
 * 便于单测直接渲染。
 *
 * 依据：UE §3.2「枚举选择器」行（W 与 T/H 必须不同）；R1/R3；
 *      架构 §2.2（不用 picker 滚轮的三条理由见 `ZiwiSelectList`）。
 */
import ZiwiSelectList, { type ZiwiOption } from './ZiwiSelectList.vue'

interface Props {
  /** 面板形态：底部浮层 / 锚定下拉 */
  variant: ZiwiPanelVariant
  /** 浮层标题（仅 `sheet` 档使用） */
  title: string
  /** 当前结果条数（仅 `sheet` 档显示） */
  count: number
  /** 是否渲染搜索框 */
  showSearch: boolean
  /** 搜索关键字（受控） */
  keyword: string
  searchPlaceholder: string
  /** 远程搜索中 */
  loading: boolean
  options: ZiwiOption[]
  modelValue: string | number | null
  displayMode: 'label' | 'code'
  middleEllipsis: boolean
  emptyKind: 'true' | 'filtered'
  objectName: string
  activeIndex: number
}

withDefaults(defineProps<Props>(), {
  title: '请选择',
  count: 0,
  showSearch: false,
  keyword: '',
  searchPlaceholder: '输入关键字搜索',
  loading: false,
  displayMode: 'label',
  middleEllipsis: false,
  emptyKind: 'true',
  objectName: '选项',
  activeIndex: -1,
})

const emit = defineEmits<{
  select: [option: ZiwiOption]
  'update:keyword': [value: string]
  close: []
  hover: [index: number]
  keydown: [event: KeyboardEvent]
}>()
</script>

<template>
  <div class="ziwi-select-panel" :class="`ziwi-select-panel--${variant}`">
    <!-- 标题栏只在底部浮层出现：下拉模式下字段 label 就在正上方，再加标题是冗余 -->
    <header v-if="variant === 'sheet'" class="ziwi-select-panel__header">
      <h3 class="ziwi-select-panel__title">{{ title }}</h3>
      <span v-if="count" class="ziwi-select-panel__count">{{ count }} 项</span>
      <button
        type="button"
        class="ziwi-select-panel__close"
        aria-label="关闭"
        @click="emit('close')"
      >
        <van-icon name="cross" size="18" />
      </button>
    </header>

    <!-- 搜索框外面包一层自己的 div：Vant Search 会把 class 透给内部 van-field，
         直接把类名写在 <van-search> 上会导致内层 field 也吃到 padding（双内边距）。 -->
    <div v-if="showSearch" class="ziwi-select-panel__search">
      <van-search
        :model-value="keyword"
        :placeholder="searchPlaceholder"
        :loading="loading"
        @update:model-value="(v: string) => emit('update:keyword', v ?? '')"
        @keydown="(e: KeyboardEvent) => emit('keydown', e)"
      />
    </div>

    <ZiwiSelectList
      :options="options"
      :model-value="modelValue"
      :display-mode="displayMode"
      :middle-ellipsis="middleEllipsis"
      :empty-kind="emptyKind"
      :keyword="keyword"
      :object-name="objectName"
      :active-index="activeIndex"
      @select="(o: ZiwiOption) => emit('select', o)"
      @hover="(i: number) => emit('hover', i)"
    />
  </div>
</template>

<style scoped>
.ziwi-select-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--ziwi-bg-white);
}

/* ── 底部浮层（T/H）：高度最多 80vh，内部列表自己滚 ── */
.ziwi-select-panel--sheet {
  max-height: 80vh;
}

/* ── 锚定下拉（W）：高度由外层容器给定，列表跟随撑满 ──
   R1「浮层内单一滚动容器」：这里不让列表再滚一层，
   改成面板整体滚动，避免出现"外层滚一段、内层滚一段"的双滚动。 */
.ziwi-select-panel--dropdown {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.ziwi-select-panel--dropdown :deep(.ziwi-select-list) {
  max-height: none;
  overflow: visible;
}

.ziwi-select-panel__header {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex: none;
  padding: var(--ziwi-gap-md) var(--ziwi-gap-lg);
  border-bottom: 1px solid var(--ziwi-border);
  min-height: var(--ziwi-actionbar-h);
}

.ziwi-select-panel__title {
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

.ziwi-select-panel__count {
  flex: none;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.ziwi-select-panel__close {
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

html[data-hover='on'] .ziwi-select-panel__close:hover {
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-primary);
}

.ziwi-select-panel__search {
  flex: none;
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border-light);
}

.ziwi-select-panel__search :deep(.van-search__content) {
  min-height: var(--ziwi-touch-min);
  align-items: center;
}
</style>
