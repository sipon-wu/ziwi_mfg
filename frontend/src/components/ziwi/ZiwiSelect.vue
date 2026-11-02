<script setup lang="ts">
/**
 * ZiwiSelect — 枚举选择器（`SelectField` 的升级体，旧名保留为薄壳）
 *
 * ## 它修掉的三件事（架构 §2.2「替换现状的 3 个坑」）
 * ① `selectedValues[0]` 陷阱：内部只认 `option.value`，不再依赖 Vant picker 的回传结构；
 * ② **内联进 `#input` 插槽**：彻底删除，改浮层 + `teleport="body"`
 *   （不 teleport 会被 Sheet 的 `overflow:hidden` 裁剪 → 表现为"点了没反应"）；
 * ③ 100 条滚轮：`options.length > 8` 强制切 `search-list`（`van-search` + 行列表），不是 picker。
 *
 * ## 两种模式（同一份面板，只差搜索框）
 * - `picker`：≤8 项，纯点击选（无滚轮、无「取消/确认」工具栏 → 不产生第二组同语义按钮，R3）
 * - `search-list`：>8 项强制出现搜索框，支持键盘上下移动 + 回车选中 + 服务端搜索 `remote`
 *
 * ## 三档形态（UE §3.2「枚举选择器」= 必须不同）
 *
 * | 形态 | 容器 | 位置 | 遮罩 | 标题栏 |
 * |---|---|---|---|---|
 * | **W** | 自绘 `fixed` 下拉 | **锚定字段下方**（空间不足翻上方） | **无** | 无 |
 * | **T** | `van-popup position="bottom"` | 视口底部 | 有 | 有 |
 * | **H** | 同上 | 视口底部 | 有 | 有 |
 *
 * ### 为什么 W 档必须换形态（B2 之前是错的）
 * 改造前三种形态共用 `position="bottom"`：在 1440 宽的一体机上选 3 个词，会从屏幕
 * 底部升起一个 **1440px 宽**的浮层把整张表格盖住，并且带遮罩、需要点关闭键才能退出。
 * 这与桌面端"下拉"的肌肉记忆完全相反（用户点字段 → 期望就地展开一个小面板）。
 * 实测几何：改造前 W/T/H 三档浮层宽度占比 1/1/1、距底 0/0/0px、面板高均 217px，
 * 即 `formFactor` 在本组件里出现 0 次。
 *
 * ### W 档为什么不加遮罩
 * 下拉是**非模态**控件：用户选完要继续看到并操作后面的字段。加遮罩会把
 * "就地选一个值"变成"进入一个模式"，多一次退出成本，且遮蔽了上下文。
 *
 * ## 清空语义
 * `clearable` 且非 disabled 时**永远**渲染清空位（不因"当前无值"而消失）；
 * 清空 emit `null`（不是 `''`，与 `inspection_order.result` 空值语义一致）；清空后焦点留在字段。
 *
 * 依据：架构 §2.2；UE §3.1 三形态、§3.2「枚举选择器」行、§4.2 长编码、§6.1 尺寸、
 *       UE-P0-01/02、UE-08/15/22；R1/R2/R3/R5。
 */
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useFormFactor } from '@/composables/useFormFactor'
import { ZIWI_SHEET_CTX } from './context'
// 面板已抽到 ZiwiSelectPanel（两档共用），这里只需要选项类型
import type { ZiwiOption } from './ZiwiSelectList.vue'
import ZiwiSelectPanel from './ZiwiSelectPanel.vue'

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
 * W 档锚定下拉
 * ------------------------------------------------------------------ */

const { isWide } = useFormFactor()

/** 字段根节点（定位锚点） */
const anchorRef = ref<HTMLElement | null>(null)
/** 下拉面板根节点（用于"点外部关闭"的命中判断） */
const dropdownRef = ref<HTMLElement | null>(null)

interface DropdownGeometry {
  top: number
  left: number
  width: number
  maxHeight: number
}

const dropdown = ref<DropdownGeometry | null>(null)

/** 下拉与字段、下拉与视口边缘的间距 */
const DROPDOWN_GAP = 4
const DROPDOWN_PAD = 8
/** 下拉最小宽度：字段很窄时（如内联小字段）也要放得下选项副行 */
const DROPDOWN_MIN_W = 240
/** 下拉最大高度（超出则面板内部滚动） */
const DROPDOWN_MAX_H = 360
/** 下方可用空间小于这个值就翻到上方展开 */
const DROPDOWN_FLIP_THRESHOLD = 200

/**
 * 依据字段当前位置算出下拉几何。
 *
 * 定位规则（R2：宽度由外层策略决定，不由内容撑开）：
 * - 宽度 = max(字段宽, 240)，再夹到视口内；
 * - 水平优先左对齐字段，右侧放不下则右对齐，仍放不下则贴左边距；
 * - 垂直优先字段下方，下方空间 < 200 且比上方更小则翻到上方。
 */
function computeDropdown(): void {
  const el = anchorRef.value
  if (!el || typeof window === 'undefined') return

  const rect = el.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight

  const width = Math.min(Math.max(rect.width, DROPDOWN_MIN_W), vw - DROPDOWN_PAD * 2)

  let left = rect.left
  if (left + width > vw - DROPDOWN_PAD) left = vw - DROPDOWN_PAD - width
  if (left < DROPDOWN_PAD) left = DROPDOWN_PAD

  const spaceBelow = vh - rect.bottom - DROPDOWN_GAP - DROPDOWN_PAD
  const spaceAbove = rect.top - DROPDOWN_GAP - DROPDOWN_PAD
  const openUp = spaceBelow < DROPDOWN_FLIP_THRESHOLD && spaceAbove > spaceBelow

  const available = Math.max(0, openUp ? spaceAbove : spaceBelow)
  const maxHeight = Math.min(DROPDOWN_MAX_H, available)
  const top = openUp
    ? Math.max(DROPDOWN_PAD, rect.top - DROPDOWN_GAP - maxHeight)
    : rect.bottom + DROPDOWN_GAP

  dropdown.value = { top, left, width, maxHeight }
}

/**
 * W 档：点击面板与字段之外的地方关闭。
 *
 * 用 `pointerdown`（而不是 `click`）是为了在字段失焦前就关掉，
 * 避免"先失焦再关"造成的闪烁。
 */
function onDocumentPointerDown(event: MouseEvent): void {
  if (!show.value || !isWide.value) return
  const target = event.target as Node | null
  if (!target) return
  if (dropdownRef.value?.contains(target)) return
  if (anchorRef.value?.contains(target)) return
  close()
}

/** W 档：页面/容器滚动时关闭（下拉是 `fixed` 定位，不跟随锚点会"飘走"） */
function onDocumentScroll(): void {
  if (!show.value || !isWide.value) return
  close()
}

function bindWideListeners(): void {
  if (typeof document === 'undefined') return
  document.addEventListener('pointerdown', onDocumentPointerDown, true)
  // capture 才能收到 Sheet 内部滚动容器的 scroll（window 上不冒泡）
  document.addEventListener('scroll', onDocumentScroll, true)
  window.addEventListener('resize', onDocumentScroll)
}

function unbindWideListeners(): void {
  if (typeof document === 'undefined') return
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
  document.removeEventListener('scroll', onDocumentScroll, true)
  window.removeEventListener('resize', onDocumentScroll)
}

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
    // 只有 T/H 档的底部浮层会占用屏幕下半部分，才需要让外层 Sheet footer 让位（R3）。
    // W 档下拉是就地展开的小面板，不动外层底部按钮，否则下拉一开一关底部会跳。
    if (open && !isWide.value) sheetContext.registerOwnedConfirm(OWNED_CONFIRM_TOKEN)
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
    if (isWide.value) {
      // 先算几何再绑监听：监听里的 close() 依赖 show，顺序无关，但几何必须在首帧前就位
      computeDropdown()
      bindWideListeners()
    }
  } else {
    if (typeof document !== 'undefined') {
      document.removeEventListener('keydown', onPopupKeydown, true)
    }
    unbindWideListeners()
  }
})

/** 形态切换（拖窗跨断点 / 旋屏）时关掉已开浮层：两种容器不通用，强行保留会错位 */
watch(isWide, () => {
  if (show.value) close()
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
  unbindWideListeners()
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

/**
 * 字段点击：W 档做开关（再点一次收起），T/H 档只开不关。
 *
 * 为什么分档：W 档是没有遮罩的就地下拉，字段本身仍可点，「点一下开、再点一下关」
 * 是桌面下拉的通行行为；T/H 档是有遮罩的模态浮层，字段已被遮罩覆盖，不存在
 * "再点一次"的场景，保持原语义即可。
 */
function toggle(): void {
  if (props.disabled) return
  if (isWide.value && show.value) {
    close()
    return
  }
  open()
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
    ref="anchorRef"
    class="ziwi-select"
    :class="[sizeClass, { 'ziwi-select--open': show }]"
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
      @click="toggle"
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

    <!-- ── W 档：锚定下拉（无遮罩、无标题栏、点外部关闭）──
         R1：绝不内联进表单流；teleport 到 body，避免被 Sheet 的 overflow 裁剪 -->
    <Teleport v-if="isWide" to="body">
      <div
        v-if="show && dropdown"
        ref="dropdownRef"
        class="ziwi-select__dropdown"
        role="dialog"
        :style="{
          '--ziwi-dd-top': `${dropdown.top}px`,
          '--ziwi-dd-left': `${dropdown.left}px`,
          '--ziwi-dd-width': `${dropdown.width}px`,
          '--ziwi-dd-max-h': `${dropdown.maxHeight}px`,
        }"
      >
        <ZiwiSelectPanel
          variant="dropdown"
          :title="popupTitle"
          :count="filteredOptions.length"
          :show-search="isSearchList"
          :keyword="keyword"
          :search-placeholder="searchPlaceholder"
          :loading="remoteLoading"
          :options="filteredOptions"
          :model-value="modelValue"
          :display-mode="displayMode"
          :middle-ellipsis="middleEllipsis"
          :empty-kind="resolvedEmptyKind"
          :object-name="objectName"
          :active-index="activeIndex"
          @select="onSelect"
          @update:keyword="onKeywordInput"
          @keydown="onFieldKeydown"
          @hover="(i: number) => (activeIndex = i)"
        />
      </div>
    </Teleport>

    <!-- ── T/H 档：底部浮层（模态，有遮罩与标题栏）── -->
    <van-popup
      v-else
      v-model:show="show"
      position="bottom"
      round
      teleport="body"
      :lock-scroll="true"
      class="ziwi-select__popup"
    >
      <ZiwiSelectPanel
        variant="sheet"
        :title="popupTitle"
        :count="filteredOptions.length"
        :show-search="isSearchList"
        :keyword="keyword"
        :search-placeholder="searchPlaceholder"
        :loading="remoteLoading"
        :options="filteredOptions"
        :model-value="modelValue"
        :display-mode="displayMode"
        :middle-ellipsis="middleEllipsis"
        :empty-kind="resolvedEmptyKind"
        :object-name="objectName"
        :active-index="activeIndex"
        @select="onSelect"
        @update:keyword="onKeywordInput"
        @keydown="onFieldKeydown"
        @close="close"
        @hover="(i: number) => (activeIndex = i)"
      />
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

/* 底部浮层（T/H）：宽度 100%，高度由内容决定，最高 80vh */
.ziwi-select__popup {
  border-radius: var(--ziwi-radius-xl) var(--ziwi-radius-xl) 0 0;
  overflow: hidden;
}

/* ── 锚定下拉（W）──
   几何由 `computeDropdown()` 在运行时算出，通过 CSS 变量注入（架构 §8.5：
   模板只注入变量，视觉属性一律留在 CSS），所以这里消费 --ziwi-dd-*。
   圆角 8 比卡片(10)小一档：浮层比页面块更轻。
   无遮罩 → 必须自带边框+阴影把面板与背后的表格分开。 */
.ziwi-select__dropdown {
  position: fixed;
  top: var(--ziwi-dd-top);
  left: var(--ziwi-dd-left);
  width: var(--ziwi-dd-width);
  max-height: var(--ziwi-dd-max-h);
  z-index: var(--ziwi-z-dropdown);
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border-card);
  border-radius: var(--ziwi-radius-lg);
  /* 阴影取 lg 而不是 md：W 档下拉最常见的落点是**白色表单浮层内部**
     （`ZiwiFormSheet` 白底），md(0 2px 8px rgba(0,0,0,.08)) 在白底上几乎看不见，
     下拉会与表单背景融为一体、看不出是一个独立的浮层。lg 才有足够边界感。 */
  box-shadow: var(--ziwi-shadow-lg);
  /* 下拉出现：缩放 + 淡入，锚点方向感（A3 层级关系 / A6 注意力引导）*/
  transform-origin: top center;
  animation: ziwi-select-drop-in var(--ziwi-motion-layer-duration)
    var(--ziwi-motion-layer-easing);
}

@keyframes ziwi-select-drop-in {
  from {
    opacity: 0;
    transform: scale(0.98) translateY(-2px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

/* 字段在打开期间的视觉回执（A2 操作已生效）：边框转主色，与下拉连成一体 */
.ziwi-select--open :deep(.van-field) {
  background: var(--ziwi-primary-bg);
}

/* 减少动效偏好：只保留状态变化，不播动画（A1 按下已注册不依赖动画） */
@media (prefers-reduced-motion: reduce) {
  .ziwi-select__dropdown {
    animation: none;
  }
}
</style>
