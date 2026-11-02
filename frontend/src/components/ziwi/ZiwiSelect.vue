<script setup lang="ts">
/**
 * ZiwiSelect — 枚举选择器（`SelectField` 的升级体，旧名保留为薄壳）
 *
 * ## 它修掉的三件事（架构 §2.2「替换现状的 3 个坑」）
 * ① `selectedValues[0]` 陷阱：内部只认 `option.value`，不再依赖 Vant picker 的回传结构；
 * ② **内联进 `#input` 插槽**：彻底删除，改 `van-popup position="bottom"` + `teleport="body"`
 *   （不 teleport 会被 Sheet 的 `overflow:hidden` 裁剪 → 表现为"点了没反应"）；
 * ③ 100 条滚轮：`options.length > 8` 强制切 `search-list`（`van-search` + 行列表），不是 picker。
 *
 * ## 两种模式（同一份 DOM 骨架，只差搜索框）
 * - `picker`：≤8 项，纯点击选（无滚轮、无「取消/确认」工具栏 → 不产生第二组同语义按钮，R3）
 * - `search-list`：>8 项强制出现搜索框，支持键盘上下移动 + 回车选中 + 服务端搜索 `remote`
 *
 * ## 清空语义
 * `clearable` 且非 disabled 时**永远**渲染清空位（不因"当前无值"而消失）；
 * 清空 emit `null`（不是 `''`，与 `inspection_order.result` 空值语义一致）；清空后焦点留在字段。
 *
 * 依据：架构 §2.2；UE §3.2「枚举选择器」行、§4.2 长编码、§6.1 尺寸、UE-P0-01/02、UE-08/15/22。
 */
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ZIWI_SHEET_CTX } from './context'
import ZiwiSelectList, { type ZiwiOption } from './ZiwiSelectList.vue'

interface Props {
  modelValue: string | number | null
  /** 选项；也接受 `string[]`（旧 SelectField 的调用方可能传字符串数组） */
  options: Array<ZiwiOption | string>
  /** 标签（作为行标签显示；为空则整行就是选择器） */
  label?: string
  /** 必填标记（仅视觉 + 无障碍，校验在页面侧） */
  required?: boolean
  placeholder?: string
  /** `auto`（默认）：options.length > 8 时强制开启搜索（§3.2） */
  searchable?: boolean | 'auto'
  searchPlaceholder?: string
  /** 服务端搜索（>200 项时必须给） */
  remote?: (keyword: string) => Promise<ZiwiOption[]>
  clearable?: boolean
  disabled?: boolean
  /** `auto` 跟随手套令牌；`normal` 裸手档；`glove` 强制手套档 */
  size?: 'auto' | 'normal' | 'glove'
  /** `code` 用于编码类字段（字段与列表都以编码为主展示） */
  displayMode?: 'label' | 'code'
  /** 长编码中间省略（§4.2） */
  middleEllipsis?: boolean
  /** 显示扫码按钮位（扫码优先于选择，UE §2.5） */
  scanEntry?: boolean
  /** 空态类型（父级可覆盖；缺省按"是否有关键字"自动判断） */
  emptyKind?: 'true' | 'filtered'
  labelWidth?: string
  /** 透传给 van-field 的规则（供 ZiwiFormSheet 定位错误） */
  rules?: unknown[]
  /** 字段名：渲染成 `data-field="<name>"`，供 Sheet 的 scrollToSelector 精确命中（UE-10） */
  fieldName?: string
  /** 浮层标题（缺省用 label 或「请选择」） */
  title?: string
  /** 无数据时的对象名，用于空态文案（如「设备」） */
  objectName?: string
}

const props = withDefaults(defineProps<Props>(), {
  label: '',
  required: false,
  placeholder: '请选择',
  searchable: 'auto',
  searchPlaceholder: '输入关键字搜索',
  clearable: true,
  disabled: false,
  size: 'auto',
  displayMode: 'label',
  middleEllipsis: false,
  scanEntry: false,
  emptyKind: undefined,
  labelWidth: '',
  rules: () => [],
  fieldName: '',
  title: '',
  objectName: '数据',
  remote: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number | null]
  change: [value: string | number | null, option: ZiwiOption | null]
  scan: []
  'search-open': []
  invalid: [message: string]
}>()

/* ------------------------------------------------------------------ *
 * 选项归一化
 * ------------------------------------------------------------------ */

/** 把 `string | ZiwiOption` 统一成 `ZiwiOption`（兼容旧 SelectField 的字符串数组） */
function normalizeOption(raw: ZiwiOption | string): ZiwiOption {
  if (typeof raw === 'string') return { label: raw, value: raw }
  return {
    label: raw.label ?? String(raw.value ?? ''),
    value: raw.value,
    code: raw.code,
    disabled: raw.disabled === true,
    desc: raw.desc,
  }
}

const normalizedOptions = computed<ZiwiOption[]>(() =>
  (Array.isArray(props.options) ? props.options : []).map(normalizeOption),
)

/* ------------------------------------------------------------------ *
 * 内部状态
 * ------------------------------------------------------------------ */

const show = ref(false)
const keyword = ref('')
/** 远程搜索结果（未使用 remote 时为 null，走本地过滤） */
const remoteOptions = ref<ZiwiOption[] | null>(null)
const remoteLoading = ref(false)
/** 键盘/扫码高亮项 */
const activeIndex = ref(-1)

const isSearchList = computed<boolean>(() => {
  if (props.searchable === 'auto') return normalizedOptions.value.length > 8
  return props.searchable === true
})

const sizeClass = computed(() => `ziwi-select--${props.size}`)

/* ------------------------------------------------------------------ *
 * 选中值 / 展示文案
 * ------------------------------------------------------------------ */

const selectedOption = computed<ZiwiOption | null>(() => {
  if (props.modelValue === null || props.modelValue === undefined) return null
  return normalizedOptions.value.find((o) => o.value === props.modelValue) ?? null
})

const hasValue = computed(
  () => props.modelValue !== null && props.modelValue !== undefined && props.modelValue !== '',
)

/** 字段展示文案：code 模式优先展示编码 */
const displayText = computed<string>(() => {
  const option = selectedOption.value
  if (!option) {
    // 服务端搜索时当前值可能不在本次结果里，仍要把值显示出来（绝不吞信息）
    if (hasValue.value) return String(props.modelValue)
    return ''
  }
  if (props.displayMode === 'code') return option.code || option.label
  return option.label
})

/* ------------------------------------------------------------------ *
 * 过滤 / 远程搜索
 * ------------------------------------------------------------------ */

let remoteTimer: ReturnType<typeof setTimeout> | null = null

const filteredOptions = computed<ZiwiOption[]>(() => {
  const source = remoteOptions.value ?? normalizedOptions.value
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return source
  return source.filter((option) => {
    const haystack = [option.label, option.code ?? '', option.desc ?? '', String(option.value)]
      .join(' ')
      .toLowerCase()
    return haystack.includes(kw)
  })
})

const resolvedEmptyKind = computed<'true' | 'filtered'>(() => {
  if (props.emptyKind) return props.emptyKind
  return keyword.value.trim() ? 'filtered' : 'true'
})

/** 远程搜索（防抖 250ms，避免每键一次请求） */
function scheduleRemoteSearch(): void {
  if (!props.remote) return
  if (remoteTimer !== null) clearTimeout(remoteTimer)
  const kw = keyword.value.trim()
  if (!kw) {
    remoteOptions.value = null
    remoteLoading.value = false
    return
  }
  remoteTimer = setTimeout(async () => {
    remoteTimer = null
    remoteLoading.value = true
    try {
      const result = await props.remote?.(kw)
      remoteOptions.value = Array.isArray(result) ? result.map(normalizeOption) : []
    } catch {
      // 搜索失败不阻塞手输/选择：退回本地结果（信息不丢）
      remoteOptions.value = null
    } finally {
      remoteLoading.value = false
    }
  }, 250)
}

watch(keyword, () => {
  activeIndex.value = -1
  scheduleRemoteSearch()
})

/* ------------------------------------------------------------------ *
 * 与 ZiwiFormSheet 的协商（R3）
 * ------------------------------------------------------------------ */

/** 本组件的"内层确认"令牌：本层打开时声明，让外层 footer 让位 */
const OWNED_CONFIRM_TOKEN: symbol = Symbol('ZiwiSelect')
const sheetContext = inject(ZIWI_SHEET_CTX, null)

watch(show, (open) => {
  if (sheetContext) {
    if (open) sheetContext.registerOwnedConfirm(OWNED_CONFIRM_TOKEN)
    else sheetContext.unregisterOwnedConfirm(OWNED_CONFIRM_TOKEN)
  }
  if (open) {
    emit('search-open')
    keyword.value = ''
    remoteOptions.value = null
    activeIndex.value = -1
    if (typeof document !== 'undefined') {
      document.addEventListener('keydown', onPopupKeydown, true)
    }
  } else if (typeof document !== 'undefined') {
    document.removeEventListener('keydown', onPopupKeydown, true)
  }
})

/**
 * 浮层打开期间的键盘处理（捕获阶段）。
 *
 * 为什么要挂 document 而不是只挂字段：浮层打开后焦点可能落在搜索框或列表上，
 * Esc / ↑↓ 仍应生效；捕获阶段 + `stopPropagation` 保证 Esc 只关本层，
 * 不会顺带把外层 ZiwiFormSheet 也关掉（层级优先）。
 *
 * @param event 键盘事件
 */
function onPopupKeydown(event: KeyboardEvent): void {
  if (!show.value) return
  if (event.key === 'Escape') {
    event.stopPropagation()
    event.preventDefault()
    close()
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter') {
    onKeydown(event)
  }
}

onBeforeUnmount(() => {
  if (remoteTimer !== null) clearTimeout(remoteTimer)
  if (typeof document !== 'undefined') {
    document.removeEventListener('keydown', onPopupKeydown, true)
  }
  sheetContext?.unregisterOwnedConfirm(OWNED_CONFIRM_TOKEN)
})

/* ------------------------------------------------------------------ *
 * 交互
 * ------------------------------------------------------------------ */

function open(): void {
  if (props.disabled) return
  show.value = true
  nextTick(() => {
    // 高亮已选项，键盘/扫码打开后立刻可回车确认
    const idx = filteredOptions.value.findIndex((o) => o.value === props.modelValue)
    activeIndex.value = idx
  })
}

function close(): void {
  show.value = false
}

/**
 * 选中一项：唯一提交出口（`update:modelValue` + `change` 成对发）。
 * @param option 被点中的选项
 */
function onSelect(option: ZiwiOption): void {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  emit('change', option.value, option)
  close()
}

/** 清空：emit `null`（不是空串），且不自动弹浮层 */
function onClear(): void {
  if (props.disabled) return
  emit('update:modelValue', null)
  emit('change', null, null)
}

function onScanClick(): void {
  emit('scan')
}

/** 搜索框输入（`v-model` 由这里统一收口） */
function onKeywordInput(value: string): void {
  keyword.value = value ?? ''
}

/** 键盘导航：↑↓ 移动、回车选中（手套场景仍可用物理键/扫码枪） */
function onKeydown(event: KeyboardEvent): void {
  if (props.disabled) return
  const list = filteredOptions.value
  if (event.key === 'ArrowDown') {
    if (!show.value) {
      open()
      event.preventDefault()
      return
    }
    event.preventDefault()
    if (list.length === 0) return
    activeIndex.value = (activeIndex.value + 1 + list.length) % list.length
    return
  }
  if (event.key === 'ArrowUp') {
    if (!show.value) return
    event.preventDefault()
    if (list.length === 0) return
    activeIndex.value = (activeIndex.value - 1 + list.length) % list.length
    return
  }
  if (event.key === 'Enter') {
    if (!show.value) {
      open()
      event.preventDefault()
      return
    }
    const target = list[activeIndex.value]
    if (target) {
      event.preventDefault()
      onSelect(target)
    }
    return
  }
  if (event.key === 'Escape' && show.value) {
    event.preventDefault()
    close()
  }
}

/** 浮层标题 */
const popupTitle = computed(() => props.title || props.label || '请选择')

/**
 * 字段/搜索框自身的键盘处理。
 *
 * 浮层打开时统一交给 document 捕获层（`onPopupKeydown`），避免同一按键被处理两次
 * （捕获 + 冒泡各走一遍会让高亮项一次跳两行）。
 */
function onFieldKeydown(event: KeyboardEvent): void {
  if (show.value) return
  onKeydown(event)
}
</script>

<template>
  <div
    class="ziwi-select"
    :class="sizeClass"
    :data-field="fieldName || undefined"
  >
    <van-field
      class="ziwi-select__field"
      :model-value="displayText"
      :label="label"
      :label-width="labelWidth || undefined"
      :required="required"
      :placeholder="placeholder"
      :disabled="disabled"
      :rules="rules as never"
      readonly
      clickable
      @click="open"
      @keydown="onFieldKeydown"
    >
      <template #button>
        <div class="ziwi-select__buttons">
          <button
            v-if="scanEntry && !disabled"
            type="button"
            class="ziwi-select__icon-btn"
            aria-label="扫码"
            @click.stop="onScanClick"
          >
            <van-icon name="scan" size="18" />
          </button>
          <button
            v-if="clearable && !disabled"
            type="button"
            class="ziwi-select__icon-btn"
            :class="{ 'ziwi-select__icon-btn--hidden': !hasValue }"
            aria-label="清空"
            @click.stop="onClear"
          >
            <van-icon name="clear" size="16" />
          </button>
        </div>
      </template>
    </van-field>

    <!-- R1：绝不内联进表单流；teleport 到 body，避免被 Sheet 的 overflow 裁剪 -->
    <van-popup
      v-model:show="show"
      position="bottom"
      round
      teleport="body"
      :lock-scroll="true"
      class="ziwi-select__popup"
    >
      <div class="ziwi-select__panel">
        <header class="ziwi-select__header">
          <h3 class="ziwi-select__title">{{ popupTitle }}</h3>
          <span v-if="filteredOptions.length" class="ziwi-select__count">
            {{ filteredOptions.length }} 项
          </span>
          <button
            type="button"
            class="ziwi-select__close"
            aria-label="关闭"
            @click="close"
          >
            <van-icon name="cross" size="18" />
          </button>
        </header>

        <!-- 搜索框外面包一层自己的 div：Vant Search 会把 class 透给内部 van-field，
             直接把类名写在 <van-search> 上会导致内层 field 也吃到 padding（视觉上双内边距）。 -->
        <div v-if="isSearchList" class="ziwi-select__search">
          <van-search
            :model-value="keyword"
            :placeholder="searchPlaceholder"
            :loading="remoteLoading"
            @update:model-value="onKeywordInput"
            @keydown="onFieldKeydown"
          />
        </div>

        <ZiwiSelectList
          :options="filteredOptions"
          :model-value="modelValue"
          :display-mode="displayMode"
          :middle-ellipsis="middleEllipsis"
          :empty-kind="resolvedEmptyKind"
          :keyword="keyword"
          :object-name="objectName"
          :active-index="activeIndex"
          @select="onSelect"
          @hover="(i: number) => (activeIndex = i)"
        />
      </div>
    </van-popup>
  </div>
</template>

<style scoped>
.ziwi-select {
  /* 热区档：auto 跟随令牌（裸手 48 / 手套 56），glove 强制 56 */
  --ziwi-select-hit: var(--ziwi-touch-min);
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.ziwi-select--glove {
  --ziwi-select-hit: 56px;
}

.ziwi-select--normal {
  --ziwi-select-hit: 48px;
}

/* 让"输入区"本身达到热区高度（UE-08 / UE-P0-02） */
.ziwi-select :deep(.van-field__body) {
  min-height: var(--ziwi-select-hit);
  align-items: center;
}

.ziwi-select :deep(.van-field__control) {
  cursor: pointer;
}

.ziwi-select__buttons {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
}

.ziwi-select__icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* 图标按钮走 --ziwi-select-hit（≥48），不再出现 22×24 那种热区（UE-P0-02） */
  min-width: var(--ziwi-select-hit);
  min-height: var(--ziwi-select-hit);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--ziwi-text-muted);
  cursor: pointer;
  border-radius: var(--ziwi-radius-md);
}

.ziwi-select__icon-btn--hidden {
  opacity: 0.25;
}

html[data-hover='on'] .ziwi-select__icon-btn:hover {
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-primary);
}

/* 浮层：宽度 100%（底部浮层），高度由内容决定，最高 80vh */
.ziwi-select__popup {
  border-radius: var(--ziwi-radius-xl) var(--ziwi-radius-xl) 0 0;
  overflow: hidden;
}

.ziwi-select__panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-height: 80vh;
  background: var(--ziwi-bg-white);
}

.ziwi-select__header {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex: none;
  padding: var(--ziwi-gap-md) var(--ziwi-gap-lg);
  border-bottom: 1px solid var(--ziwi-border);
  min-height: var(--ziwi-actionbar-h);
}

.ziwi-select__title {
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

.ziwi-select__count {
  flex: none;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.ziwi-select__close {
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

html[data-hover='on'] .ziwi-select__close:hover {
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-primary);
}

.ziwi-select__search {
  flex: none;
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  background: var(--ziwi-bg-white);
}

/* 搜索框本体的热区由令牌保证（UE-08） */
.ziwi-select__search :deep(.van-search__content) {
  min-height: var(--ziwi-select-hit);
  align-items: center;
}
</style>
