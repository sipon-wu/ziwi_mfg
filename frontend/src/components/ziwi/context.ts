/**
 * Ziwi 设计系统 · 容器上下文（架构 §5.1 / §8.6）
 *
 * 这个文件只做两件事：
 * 1. 定义 `provide/inject` 的 Key 与载荷类型（T02 的 `ZiwiFormSheet` / `ZiwiSelect`
 *    等容器组件靠它把"当前处于什么容器里"告诉子组件）；
 * 2. 定义容器组件的公共枚举（形态、尺寸档、关闭策略），避免各组件各写一套字面量。
 *
 * 硬规则（架构 §8.6）：`components/ziwi/*` 不得 import `pages/*` 或 `api/*`（纯展示）。
 * 因此本文件**只能**依赖 `config/` 与 `vue`，不得依赖 router / store / axios。
 */
import type { ComputedRef, InjectionKey, Ref } from 'vue'
import type { FormFactor } from '@/config/formFactor'

/** 浮层容器形态：与 FormFactor 一一对应（W 居中 dialog / T 侧抽屉 / H 全屏页） */
export type SheetVariant = 'dialog' | 'drawer' | 'page'

/** 尺寸档 */
export type SheetSize = 'sm' | 'md' | 'lg' | 'full'

/**
 * 遮罩点击策略。
 * 依据 UE §6.3「误滑关闭」：含未保存数据的浮层禁止下滑关闭；
 * 点击遮罩必须全站一致。
 */
export type SheetMaskPolicy = 'close' | 'confirm' | 'disabled'

/** 浮层滚动策略。依据 §3.3 R1：浮层自身是唯一滚动容器 */
export type SheetScrollPolicy = 'self' | 'none'

/** 表单浮层向子组件暴露的上下文 */
export interface ZiwiSheetContext {
  /** 当前容器形态 */
  variant: SheetVariant
  /** 当前形态（W/T/H），便于子组件做更细的分支 */
  formFactor: ComputedRef<FormFactor>
  /** 尺寸档 */
  size: SheetSize
  /** 是否处于打开状态 */
  opened: Readonly<Ref<boolean>>
  /** 是否有未保存内容（由 ZiwiFormSheet 与 useDirtyGuard 联动写入） */
  dirty: Ref<boolean>
  /** 请求关闭（内部会按 maskPolicy / dirty 决定是否真的关） */
  requestClose: (reason?: string) => void
  /** 关闭浮层（跳过确认，仅在确认之后调用） */
  close: () => void
  /** 注册一个"关闭前"钩子，返回解绑函数 */
  onBeforeClose: (hook: () => boolean | Promise<boolean>) => () => void
  /** 把容器滚动到顶部（分步表单前进/后退时用） */
  scrollToTop: () => void
}

/** 注入 Key：ZIWI_SHEET_CTX */
export const ZIWI_SHEET_CTX: InjectionKey<ZiwiSheetContext> = Symbol('ZIWI_SHEET_CTX')

/** 表单容器向"字段"暴露的上下文（错误摘要 ↔ 字段就近错误的联动） */
export interface ZiwiFormFieldContext {
  /** 注册字段，返回注销函数。用于"第一个错误字段"定位 */
  registerField: (name: string, el: () => HTMLElement | null) => () => void
  /** 报告字段错误 */
  setFieldError: (name: string, message: string | null) => void
  /** 读取字段错误 */
  getFieldError: (name: string) => string | null
  /** 把视口滚动到某字段并聚焦 */
  focusField: (name: string) => boolean
}

/** 注入 Key：ZIWI_FORM_FIELD_CTX */
export const ZIWI_FORM_FIELD_CTX: InjectionKey<ZiwiFormFieldContext> = Symbol(
  'ZIWI_FORM_FIELD_CTX',
)

/** 底部主操作条向子组件暴露的上下文 */
export interface ZiwiActionBarContext {
  /** 操作条高度（含 safe-area），子组件用于计算让位 padding */
  height: ComputedRef<string>
  /** 是否固定底部（H/T 为 true，W 为 false） */
  isFixed: ComputedRef<boolean>
  /** 主操作是否处于提交中（用于禁用 + 文案切换） */
  submitting: Readonly<Ref<boolean>>
}

/** 注入 Key：ZIWI_ACTION_BAR_CTX */
export const ZIWI_ACTION_BAR_CTX: InjectionKey<ZiwiActionBarContext> = Symbol(
  'ZIWI_ACTION_BAR_CTX',
)

/**
 * 形态 → 浮层容器的映射（UE §3.2「新建/编辑表单」行）。
 *
 * | 形态 | 容器 |
 * |---|---|
 * | W | 居中浮层（宽度按视口比例上限，内容整体滚动） |
 * | T | 右侧抽屉（近全宽）或半屏浮层 |
 * | H | 全屏页，底部固定主操作 |
 *
 * @param formFactor 当前形态
 */
export function sheetVariantOf(formFactor: FormFactor): SheetVariant {
  if (formFactor === 'H') return 'page'
  if (formFactor === 'T') return 'drawer'
  return 'dialog'
}

/**
 * 形态 → 是否固定底部主操作条（UE-03 / §3.3 R4）。
 *
 * @param formFactor 当前形态
 */
export function actionBarIsFixed(formFactor: FormFactor): boolean {
  return formFactor === 'H' || formFactor === 'T'
}

/**
 * 形态 → 遮罩点击策略的默认值。
 * W/T 有遮罩；H 是全屏页无遮罩。
 *
 * @param variant 容器形态
 */
export function defaultMaskPolicy(variant: SheetVariant): SheetMaskPolicy {
  return variant === 'page' ? 'disabled' : 'confirm'
}
