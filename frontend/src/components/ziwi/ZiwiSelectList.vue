<script lang="ts">
/**
 * 选项结构。放在列表组件里导出，作为 `ZiwiSelect` / `ZiwiSelectList` / 业务页共享的**唯一**形状
 * （架构 §2.2 `ZiwiOption`）。避免各处再写一遍导致 `code` / `desc` 字段名漂移。
 */
export interface ZiwiOption {
  /** 主文案（人读的名字） */
  label: string
  /** 提交值（数字与字符串都允许，后端 id 常为 number） */
  value: string | number
  /** 编码（列表副行 / `displayMode="code"` 时作为主展示） */
  code?: string
  /** 禁用项（不可选，但仍可见 —— UE-14：不静默消失） */
  disabled?: boolean
  /** 描述（副行第二段，如规格/库位） */
  desc?: string
}
</script>

<script setup lang="ts">
/**
 * ZiwiSelectList — 搜索型/平铺型选项列表（`ZiwiSelect` 的内部件）
 *
 * 为什么不用 `van-picker` 滚轮：
 * 1. 滚轮在手套下几乎无法精确停在目标项（UE §6.1 手套档 56px 行高后一屏只能显示 5 行）；
 * 2. 滚轮自带「取消/确认」工具栏 → 与外层 Sheet 形成第二组同语义按钮（R3 / UE-P0-04）；
 * 3. 100 条数据在滚轮里翻页成本极高（架构 §2.2 坑③）。
 *
 * 因此这里统一成「列表行 + 点击即选」：一次点击完成选择，且**不渲染任何 picker**。
 *
 * 依据：架构 §2.2；UE §3.2「枚举选择器」行、§4.3 列表行信息层级、§6.1 尺寸。
 */
import { computed } from 'vue'

interface Props {
  /** 选项（已由父级按关键字过滤） */
  options: ZiwiOption[]
  /** 当前值 */
  modelValue: string | number | null
  /** 主展示取 label 还是 code */
  displayMode?: 'label' | 'code'
  /** 长编码中间省略（§4.2） */
  middleEllipsis?: boolean
  /** 空态类型：真无数据 / 筛选无结果（复用四类空态口径，§5.1） */
  emptyKind?: 'true' | 'filtered'
  /** 空态时回显的筛选条件（emptyKind='filtered' 用） */
  keyword?: string
  /** 真无数据时的对象名，如「设备」 */
  objectName?: string
  /** 键盘/扫码高亮项下标（-1 表示无） */
  activeIndex?: number
}

const props = withDefaults(defineProps<Props>(), {
  displayMode: 'label',
  middleEllipsis: false,
  emptyKind: 'true',
  keyword: '',
  objectName: '选项',
  activeIndex: -1,
})

const emit = defineEmits<{
  /** 选中一项 */
  select: [option: ZiwiOption]
  /** 鼠标/触摸移到某行（供父级同步 activeIndex） */
  hover: [index: number]
}>()

const visibleOptions = computed<ZiwiOption[]>(() =>
  Array.isArray(props.options) ? props.options : [],
)

/** 列表主文案：code 模式优先展示编码 */
function primaryText(option: ZiwiOption): string {
  if (props.displayMode === 'code') return option.code || option.label
  return option.label
}

/** 列表副行：编码 + 描述（两者都有时用间隔号连接） */
function secondaryText(option: ZiwiOption): string {
  const parts: string[] = []
  if (props.displayMode !== 'code' && option.code) parts.push(option.code)
  if (option.desc) parts.push(option.desc)
  return parts.join(' · ')
}

function isSelected(option: ZiwiOption): boolean {
  if (props.modelValue === null || props.modelValue === undefined) return false
  return option.value === props.modelValue
}

function onSelect(option: ZiwiOption): void {
  if (option.disabled) return
  emit('select', option)
}

function onHover(index: number): void {
  emit('hover', index)
}
</script>

<template>
  <div class="ziwi-select-list" role="listbox">
    <template v-if="visibleOptions.length > 0">
      <div
        v-for="(option, index) in visibleOptions"
        :key="`${option.value}`"
        class="ziwi-select-list__row"
        :class="{
          'ziwi-select-list__row--selected': isSelected(option),
          'ziwi-select-list__row--active': index === activeIndex,
          'ziwi-select-list__row--disabled': option.disabled === true,
        }"
        role="option"
        :aria-selected="isSelected(option)"
        :aria-disabled="option.disabled === true"
        @click="onSelect(option)"
        @mouseenter="onHover(index)"
      >
        <div class="ziwi-select-list__text">
          <div
            class="ziwi-select-list__label"
            :class="{ 'ziwi-select-list__label--mono': displayMode === 'code' }"
          >
            <span
              :class="
                middleEllipsis && displayMode === 'code' ? 'ziwi-select-list__ellipsis' : ''
              "
              :title="primaryText(option)"
            >
              {{ primaryText(option) }}
            </span>
          </div>
          <div v-if="secondaryText(option)" class="ziwi-select-list__sub">
            {{ secondaryText(option) }}
          </div>
        </div>
        <van-icon
          v-if="isSelected(option)"
          class="ziwi-select-list__check"
          name="success"
          size="18"
        />
      </div>
    </template>

    <!-- 空态：真无数据 vs 筛选无结果，文案与动作必须不同（§5.1 / UE-12） -->
    <div v-else class="ziwi-select-list__empty">
      <template v-if="emptyKind === 'filtered'">
        <p class="ziwi-select-list__empty-title">
          当前条件下没有{{ objectName }}
        </p>
        <p class="ziwi-select-list__empty-hint">
          已按「{{ keyword }}」筛选，换个关键字试试
        </p>
      </template>
      <template v-else>
        <p class="ziwi-select-list__empty-title">还没有{{ objectName }}可选</p>
        <p class="ziwi-select-list__empty-hint">先到对应模块建一条数据，再回到这里选择</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.ziwi-select-list {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  /* 列表自身滚动，但与 Sheet 是**两个不同浮层**，不构成嵌套滚动（R1 只约束同一层） */
  max-height: 60vh;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}

.ziwi-select-list__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  /* 行高走令牌：裸手 48 / 手套 56（UE-08 / UE-P0-02） */
  min-height: var(--ziwi-row-min-h);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-lg);
  border-bottom: 1px solid var(--ziwi-border-light);
  cursor: pointer;
  /* 触屏必须有按下反馈（A1：按下已注册）—— 用 tap 档，不是固定 60ms */
  transition: background-color var(--ziwi-motion-tap-duration) var(--ziwi-motion-tap-easing);
}

.ziwi-select-list__row:active {
  background: var(--ziwi-primary-bg);
}

/* 悬停只作增强（R5）：只在有精确指针时出现 */
html[data-hover='on'] .ziwi-select-list__row:hover {
  background: var(--ziwi-bg-light);
}

.ziwi-select-list__row--active {
  background: var(--ziwi-bg-light);
}

.ziwi-select-list__row--selected {
  background: var(--ziwi-primary-bg);
}

.ziwi-select-list__row--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ziwi-select-list__text {
  flex: 1 1 auto;
  min-width: 0;
}

.ziwi-select-list__label {
  font-size: var(--ziwi-font-size-lg);
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-text-primary);
  /* R2：长名称不得撑开外层 */
  min-width: 0;
  overflow-wrap: anywhere;
}

.ziwi-select-list__label--mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: 0.02em;
}

/* 长编码中间省略：保留首尾（§4.2） */
.ziwi-select-list__ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl;
  text-align: left;
}

.ziwi-select-list__sub {
  margin-top: var(--ziwi-gap-2xs);
  font-size: var(--ziwi-font-size-sm);
  line-height: var(--ziwi-lineheight-tight);
  color: var(--ziwi-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ziwi-select-list__check {
  flex: none;
  color: var(--ziwi-primary);
}

.ziwi-select-list__empty {
  padding: var(--ziwi-gap-2xl) var(--ziwi-gap-lg);
  text-align: center;
}

.ziwi-select-list__empty-title {
  margin: 0;
  font-size: var(--ziwi-font-size-lg);
  color: var(--ziwi-text-secondary);
}

.ziwi-select-list__empty-hint {
  margin: var(--ziwi-gap-sm) 0 0;
  font-size: var(--ziwi-font-size-sm);
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-text-muted);
}
</style>
