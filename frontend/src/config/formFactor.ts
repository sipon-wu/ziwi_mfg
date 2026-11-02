/**
 * 形态判定唯一真源（Form Factor）
 *
 * 依据：`docs/ue-interaction-spec-2026-11-02.md` §3.1 三种运行形态
 *
 * | 标记 | 判定条件 | 典型设备 |
 * |---|---|---|
 * | **W** 宽屏 | 视口宽 ≥ 1024 且横屏 | 工位一体机 21.5"/24"（纯触屏）、办公 PC |
 * | **T** 中屏 | 600 ≤ 视口宽 < 1024（横屏），或竖屏且宽 ≥ 768 | 10" 平板、横置手持大屏机 |
 * | **H** 手持 | 视口宽 < 600，或竖屏且宽 < 768 | PDA、扫码手机、5–6" 工业手持机 |
 *
 * ## 判定原则：**纯宽度主判据**（2026-11 修订）
 *
 * 形态只由「视口宽 + 横竖屏」决定，**输入能力（是否有悬停）不参与判定**。
 * `hasHover` 保留在 {@link FormFactorResult} 里，但降级为 W 档内部的**增强标志**，
 * 仅用于「是否启用 hover 态 / 是否允许密集小控件」，不改变浮层形态。
 *
 * ### 为什么移除 `hasHover` 前置条件（历史 bug）
 *
 * 早期实现把 `hasHover` 当作 W 的**必要条件**：
 *
 * ```ts
 * } else if (!isPortrait && hasHover && width > BREAKPOINTS.MEDIUM) { formFactor = 'W' }
 * ```
 *
 * 后果：任何**纯触屏大屏**永远拿不到 W。车间工位一体机 21.5"/24" 正是纯触屏、
 * 无悬停 —— 一台 1920×1080 的一体机会被判成 `T`（浮层退化成 720px 抽屉），
 * 而一台带鼠标的 1440 笔记本反而是 `W`。这与现场实际（「车间现场几乎全用触屏」）
 * 完全相反。输入能力是**能力探测**，不该反过来决定**布局形态**。
 *
 * ### 边界归属（实现约定，务必遵守）
 *
 * UE 原文给出 T 带为半开区间 `[600, 1024)`，W 带写作 `≥ 1024`，两者在 `1024`
 * 这一点相邻重叠。实现上必须为 `1024` 选定唯一归属，否则拖窗到 1024 时会出现两套
 * 样式互相覆盖。此处取 **W**（较宽的一档），理由是：
 *
 * 1. UE §3.1 原文即为「视口宽 ≥1024 且横屏 = W」，取 W 是**回归文档原文**，
 *    不再额外引入实现侧的退让约定；
 * 2. 1024×768 是**工业现场一体机**的实测尺寸之一。若归 T，抽屉占 720px 只剩
 *    304px 背景（约 30%），视觉上等同于跳页 —— 失去了「浮层是浮层」的空间线索，
 *    用户会误以为已经离开列表页。这正是 T02 验收里暴露出来的问题；
 * 3. 早期「向信息密度更低的一档退让更安全」的推理前提（1024 处输入能力多为触屏）
 *    已被证伪：T02 之后 W 档不再要求悬停，触屏也能安全承载 W 的多列布局。
 *
 * 因此最终生效的带宽为：
 *
 * ```
 * H: [0, 600)  ∪  (竖屏 且 [0, 768))
 * T: [600, 1024)  横屏   ∪  (竖屏 且 [768, +∞))
 * W: [1024, +∞)   横屏
 * ```
 *
 * 三个区间互不相交、并集为全体正数宽度，**不存在重叠**（T 右端开、W 左端闭）。
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
  /**
   * T / W 分界。**宽 ≥ 1024 且横屏即为 W**（取 W，见文件头「边界归属」）。
   * 注意：该阈值是**闭区间左端点**，`width === 1024` 属于 W，不是 T。
   */
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
  /**
   * 主输入设备是否支持悬停（`matchMedia('(hover: hover)')`）。
   *
   * **不参与形态判定**，仅作为 W 档内部的增强标志向下传递。
   */
  hasHover: boolean
}

/** 判定结果，附带派生标记，供组件按需取用而不必重复计算 */
export interface FormFactorResult {
  formFactor: FormFactor
  width: number
  height: number
  /**
   * 主输入设备是否可悬停。**仅作增强标志**：用于决定是否启用 `:hover` 态
   * （R5：悬停只作增强）、是否允许密集小控件。**绝不用于改变形态。**
   */
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
 * 判定次序（短路，先窄后宽）：
 * 1. `width < 600` → H
 * 2. 竖屏 且 `width < 768` → H
 * 3. 横屏 且 `width ≥ 1024` → W
 * 4. 其余 → T
 *
 * @param input 视口尺寸与输入能力（输入能力不参与判定）
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
    // 竖屏且宽 < 768：手持（如 750×1334 竖屏手机）
    formFactor = 'H'
  } else if (!isPortrait && width >= BREAKPOINTS.MEDIUM) {
    // 横屏 + 宽 ≥ 1024：宽屏。★ 不判断 hasHover —— 纯触屏一体机同样是 W
    formFactor = 'W'
  } else {
    // 600 ≤ 宽 < 1024 的横屏；或竖屏且宽 ≥ 768（不含横屏 W 条件）：中屏
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
