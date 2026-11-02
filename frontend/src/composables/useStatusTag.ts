/**
 * 状态标签取值 Composable（架构 §8.2 第 2 条）
 *
 * `useStatusTag(domain, code)` → `{ label, semantic, icon, cssVars, tagType }`
 *
 * 为什么返回 `cssVars` 而不只是颜色字符串：颜色必须来自 CSS 令牌
 * （`--ziwi-state-*`），组件把这几个变量注入到元素上即可，JS 侧不持有色值。
 * 这样"改配色"只需要改 CSS，"改文案/图标"只需要改 statusDict.ts，两边不交叉。
 *
 * 双编码（UE §1.2 / §3.2）：`label` + `icon` 必须同时渲染，二者缺一即为违规。
 * 本 composable 不负责渲染，只保证取值层面两者都拿得到。
 */
import { computed, type ComputedRef } from 'vue'
import {
  getStateEntry,
  listStatusCodes,
  type StateEntry,
  type StateSemantic,
} from '@/config/statusDict'

/** Vant Tag 支持的 type 值（用于需要落到 van-tag 的场景） */
export type VantTagType = 'primary' | 'success' | 'warning' | 'danger' | 'default'

/** 语义档 → Vant Tag type 的桥接（只为兼容既有 van-tag 用法） */
const SEMANTIC_TO_VANT: Record<StateSemantic, VantTagType> = {
  neutral: 'default',
  progress: 'primary',
  success: 'success',
  warning: 'warning',
  danger: 'danger',
}

/** 语义档 → CSS 变量名后缀（必须与 styles/ziwi-tokens.css 一致） */
const SEMANTIC_VARS: Record<StateSemantic, { fg: string; bg: string; bd: string }> = {
  neutral: {
    fg: '--ziwi-state-neutral-fg',
    bg: '--ziwi-state-neutral-bg',
    bd: '--ziwi-state-neutral-bd',
  },
  progress: {
    fg: '--ziwi-state-progress-fg',
    bg: '--ziwi-state-progress-bg',
    bd: '--ziwi-state-progress-bd',
  },
  success: {
    fg: '--ziwi-state-success-fg',
    bg: '--ziwi-state-success-bg',
    bd: '--ziwi-state-success-bd',
  },
  warning: {
    fg: '--ziwi-state-warning-fg',
    bg: '--ziwi-state-warning-bg',
    bd: '--ziwi-state-warning-bd',
  },
  danger: {
    fg: '--ziwi-state-danger-fg',
    bg: '--ziwi-state-danger-bg',
    bd: '--ziwi-state-danger-bd',
  },
}

/** useStatusTag 的返回结构 */
export interface StatusTag {
  /** 文案（双编码之一） */
  label: ComputedRef<string>
  /** 语义档 */
  semantic: ComputedRef<StateSemantic>
  /** 图标名（双编码之二） */
  icon: ComputedRef<string>
  /** 排序权重 */
  order: ComputedRef<number>
  /** 是否需立即处理 */
  actionable: ComputedRef<boolean>
  /** 可直接 `:style` 绑定的 CSS 变量对象（色值只在 CSS 里） */
  cssVars: ComputedRef<Record<string, string>>
  /** 语义档类名：`ziwi-state ziwi-state--success` */
  className: ComputedRef<string>
  /** 兼容 van-tag 的 type */
  tagType: ComputedRef<VantTagType>
}

/**
 * 取状态标签。
 *
 * @param domain 字典域（`config/statusDict.ts` 的 key）
 * @param code 状态码（可以是 Ref，也可是字面量；空串是合法码）
 */
export function useStatusTag(
  domain: string,
  code: string | null | undefined | (() => string | null | undefined),
): StatusTag {
  const resolveCode = (): string => {
    const raw = typeof code === 'function' ? code() : code
    return raw === null || raw === undefined ? '' : String(raw)
  }

  const entry = computed<StateEntry>(() => getStateEntry(domain, resolveCode()))

  const label = computed(() => entry.value.label)
  const semantic = computed(() => entry.value.semantic)
  const icon = computed(() => entry.value.icon)
  const order = computed(() => entry.value.order)
  const actionable = computed(() => entry.value.actionable === true)

  /**
   * 可直接 `:style` 绑定的 CSS 变量对象。
   *
   * 用途：极少数拿不到 .ziwi-state 类的场景（如需要就地覆盖第三方组件皮肤、
   * 或把状态色透传给内部子元素）。**JS 侧不持有任何色值**，只做变量转发，
   * 因此改配色仍然只需要改 styles/ziwi-tokens.css。
   *
   * 用法：`:style="tag.cssVars"` 后，模板里写 `color: var(--ziwi-tag-fg)`。
   */
  const cssVars = computed<Record<string, string>>(() => {
    const vars = SEMANTIC_VARS[semantic.value]
    return {
      '--ziwi-tag-fg': `var(${vars.fg})`,
      '--ziwi-tag-bg': `var(${vars.bg})`,
      '--ziwi-tag-bd': `var(${vars.bd})`,
    }
  })

  const className = computed(() => `ziwi-state ziwi-state--${semantic.value}`)
  const tagType = computed<VantTagType>(() => SEMANTIC_TO_VANT[semantic.value])

  return { label, semantic, icon, order, actionable, cssVars, className, tagType }
}

/**
 * 非组件环境（如表单校验、导出、静态闸）直接取值。
 *
 * @param domain 字典域
 * @param code 状态码
 */
export function resolveStatusLabel(domain: string, code: string | null | undefined): string {
  return getStateEntry(domain, code).label
}

/**
 * 某 domain 的全部状态码，用于筛选下拉。
 *
 * @param domain 字典域
 */
export function statusCodesOf(domain: string): string[] {
  return listStatusCodes(domain)
}
