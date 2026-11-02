/**
 * 形态判定唯一真源（Form Factor）
 *
 * 依据：`docs/ue-interaction-spec-2026-11-02.md` §3.1 三种运行形态
 *
 * | 标记 | 判定条件 | 典型设备 |
 * |---|---|---|
 * | **W** 宽屏 | 视口宽 ≥ 1024 且横屏 | 工位一体机 21.5"/24"、办公 PC |
 * | **T** 中屏 | 600 ≤ 视口宽 < 1024，或宽度 ≥1024 但为纯触屏（无悬停） | 10" 平板、横置手持大屏机 |
 * | **H** 手持 | 视口宽 < 600，或竖屏且宽 < 768 | PDA、扫码手机、5–6" 工业手持机 |
 *
 * ## 边界归属（实现约定，务必遵守）
 *
 * UE 原文给出的 T 带是**半开区间** `[600, 1024)`，而 W 带写作 `≥ 1024`，两者在 `1024`
 * 这一点相邻重叠。实现上必须为 `1024` 选定唯一归属，否则拖窗到 1024 时会出现两套样式
 * 互相覆盖。此处取 **T**（较窄的一档），理由是：
 *
 * 1. 与 T 带的半开区间写法自洽，不会出现"T 的右端点其实属于 W"的自相矛盾；
 * 2. 1024 宽是**工位一体机（触摸）**的实测尺寸，实际输入能力多为触屏；
 * 3. 边界处向"信息密度更低"的一档退让，比向"更密"的一档退让更安全（宁可减列，不可塌陷）。
 *
 * 因此最终生效的带宽为：
 *
 * ```
 * H: [0, 600)  ∪  (竖屏 且 [0, 768))
 * T: [600, 1024]
 * W: (1024, +∞) 且横屏且具备悬停能力
 * ```
 *
 * 该文件**不含任何 DOM 操作**，可被单元测试直接引入；副作用只发生在
 * `composables/useFormFactor.ts`。
 */

/** 断点阈值（px）。**唯一真源**，CSS 侧只做镜像，见 `styles/ziwi-tokens.css`。 */
export const BREAKPOINTS = {
  /** H 形态上界（宽）。宽 < 600 一律手持 */
  HANDHELD: 600,
  /** 竖屏时 H 形态上界。竖屏且宽 < 768 一律手持 */
  PORTRAIT_MAX: 768,
  /** T / W 分界。宽 > 1024 且横屏且有悬停能力才是 W */
  MEDIUM: 1024,
} as const

/** 三种运行形态 */
export type FormFactor = 'W' | 'T' | 'H'

/** 判定入参。全部显式给出，便于在无 DOM 环境下测试 */
export interface FormFactorInput {
  /** 视口宽（CSS px） */
  width: number
  /** 视口高（CSS px） */
  height: number
  /** 主输入设备是否支持悬停（`matchMedia('(hover: hover)')`） */
  hasHover: boolean
}

/** 判定结果，附带派生标记，供组件按需取用而不必重复计算 */
export interface FormFactorResult {
  formFactor: FormFactor
  width: number
  height: number
  hasHover: boolean
  /** 竖屏（height > width） */
  isPortrait: boolean
  /** 是否手持形态 */
  isHandheld: boolean
  /** 是否中屏形态 */
  isMedium: boolean
  /** 是否宽屏形态 */
  isWide: boolean
}

/**
 * 兜底形态：无 `window`（SSR / 单测 / 构建期）时按办公 PC 处理。
 * 选 W 而不是 H，是因为后台管理系统的默认使用场景是桌面；退化成 W 只会少减列，
 * 退化成 H 会让桌面用户看到卡片流。
 */
export const DEFAULT_FORM_FACTOR: FormFactor = 'W'

/** 把任意字符串收敛为合法形态，非法值回落到 {@link DEFAULT_FORM_FACTOR} */
export function normalizeFormFactor(raw: unknown): FormFactor {
  return raw === 'W' || raw === 'T' || raw === 'H' ? raw : DEFAULT_FORM_FACTOR
}

/**
 * 形态判定（纯函数）。
 *
 * @param input 视口尺寸与输入能力
 * @returns 判定结果
 */
export function resolveFormFactor(input: FormFactorInput): FormFactorResult {
  const width = Number.isFinite(input.width) ? Math.max(0, input.width) : 0
  const height = Number.isFinite(input.height) ? Math.max(0, input.height) : 0
  const hasHover = input.hasHover === true
  const isPortrait = height > width

  let formFactor: FormFactor
  if (width < BREAKPOINTS.HANDHELD) {
    // 宽 < 600：无论横竖屏都是手持
    formFactor = 'H'
  } else if (isPortrait && width < BREAKPOINTS.PORTRAIT_MAX) {
    // 竖屏且宽 < 768：手持
    formFactor = 'H'
  } else if (!isPortrait && hasHover && width > BREAKPOINTS.MEDIUM) {
    // 横屏 + 有悬停 + 宽 > 1024：宽屏
    formFactor = 'W'
  } else {
    // 600 ≤ 宽 ≤ 1024，或宽 > 1024 但纯触屏 / 竖屏：中屏
    formFactor = 'T'
  }

  return {
    formFactor,
    width,
    height,
    hasHover,
    isPortrait,
    isHandheld: formFactor === 'H',
    isMedium: formFactor === 'T',
    isWide: formFactor === 'W',
  }
}
