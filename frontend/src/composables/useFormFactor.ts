/**
 * 形态判定的响应式单例。
 *
 * 职责（只做三件事）：
 * 1. 监听视口变化与输入能力变化 —— **拖窗即时变，不要求刷新**（UE §3.1 第 3 条）；
 * 2. 把结果下发到 `<html data-form-factor="W|T|H">`，全站 CSS 只认这一个属性；
 * 3. 对外提供只读 Ref，供组件做形态分支。
 *
 * 不使用 `@vueuse/core`（架构 §6 明确不引入），只用原生 `matchMedia` + `resize`。
 * 监听只在首次 `installFormFactor()` 时注册一次；`app` 参数仅为签名对齐，未使用。
 *
 * ★ 输入能力与形态解耦：`hasHover` 只下发到 `<html data-hover="on|off">` 作悬停增强
 *   （R5），**不参与** `data-form-factor` 的判定。纯触屏一体机（1920×1080 无悬停）
 *   依然是 W。详见 `config/formFactor.ts` 文件头。
 */
import { computed, readonly, ref, type App, type ComputedRef, type Ref } from 'vue'
import {
  DEFAULT_FORM_FACTOR,
  resolveFormFactor,
  type FormFactor,
  type FormFactorResult,
} from '@/config/formFactor'

/** `<html>` 上的形态属性名（架构 §8.1：data 属性全局唯一） */
export const FORM_FACTOR_ATTR = 'formFactor'

/** matchMedia 查询：(hover: hover) 表示主输入设备可悬停且指针精确 */
const HOVER_QUERY = '(hover: hover)'

/** 单例状态 */
const formFactor = ref<FormFactor>(DEFAULT_FORM_FACTOR)
const width = ref(0)
const height = ref(0)
const hasHover = ref(true)
const isPortrait = ref(false)

/** 已注册的清理函数；重复 install 时先解除旧监听，避免 HMR 下监听堆叠 */
let disposeListeners: (() => void) | null = null

/** 是否有 window（SSR / 单测守卫） */
function canUseDom(): boolean {
  return typeof window !== 'undefined' && typeof document !== 'undefined'
}

/**
 * 读取当前环境并刷新全部状态。
 * @returns 刷新后的判定结果
 */
function readEnvironment(): FormFactorResult {
  if (!canUseDom()) {
    const fallback = resolveFormFactor({ width: 0, height: 0, hasHover: true })
    formFactor.value = fallback.formFactor
    return fallback
  }
  const hoverMedia = window.matchMedia(HOVER_QUERY)
  const result = resolveFormFactor({
    width: window.innerWidth,
    height: window.innerHeight,
    hasHover: hoverMedia.matches,
  })
  formFactor.value = result.formFactor
  width.value = result.width
  height.value = result.height
  hasHover.value = result.hasHover
  isPortrait.value = result.isPortrait
  return result
}

/**
 * 把形态写到 `<html data-form-factor>`。
 * 这是全站形态样式的**唯一**开关；CSS 侧无需知道判定细节。
 */
function applyToDocument(result: FormFactorResult): void {
  if (!canUseDom()) return
  const root = document.documentElement
  if (root.dataset[FORM_FACTOR_ATTR] !== result.formFactor) {
    root.dataset[FORM_FACTOR_ATTR] = result.formFactor
  }
  // 供 CSS 做"是否需要悬停增强"的分支（R5：悬停只作增强）
  const hoverFlag = result.hasHover ? 'on' : 'off'
  if (root.dataset.hover !== hoverFlag) {
    root.dataset.hover = hoverFlag
  }
}

/** 刷新一次：判定 → 下发 */
function refresh(): void {
  applyToDocument(readEnvironment())
}

/**
 * 安装形态监听（幂等）。应在 `app.mount()` 之前调用。
 *
 * @param _app Vue 应用实例（保留位置，便于未来注入 provide）
 * @returns 卸载函数
 */
export function installFormFactor(_app?: App): () => void {
  if (!canUseDom()) return () => {}

  // 先同步算一次，保证首帧就有正确的 data-form-factor
  refresh()

  // 拖窗 / 旋屏：resize 已覆盖，无需再监听 orientationchange
  let frame = 0
  const onResize = (): void => {
    if (frame) return
    frame = window.requestAnimationFrame(() => {
      frame = 0
      refresh()
    })
  }

  const hoverMedia = window.matchMedia(HOVER_QUERY)
  const onHoverChange = (): void => refresh()

  window.addEventListener('resize', onResize, { passive: true })
  window.addEventListener('orientationchange', onResize, { passive: true })
  // Safari < 14 只有 addListener
  if (typeof hoverMedia.addEventListener === 'function') {
    hoverMedia.addEventListener('change', onHoverChange)
  } else if (typeof (hoverMedia as MediaQueryList).addListener === 'function') {
    ;(hoverMedia as MediaQueryList).addListener(onHoverChange)
  }

  const dispose = (): void => {
    if (frame) {
      window.cancelAnimationFrame(frame)
      frame = 0
    }
    window.removeEventListener('resize', onResize)
    window.removeEventListener('orientationchange', onResize)
    if (typeof hoverMedia.removeEventListener === 'function') {
      hoverMedia.removeEventListener('change', onHoverChange)
    } else if (typeof (hoverMedia as MediaQueryList).removeListener === 'function') {
      ;(hoverMedia as MediaQueryList).removeListener(onHoverChange)
    }
    disposeListeners = null
  }

  disposeListeners?.()
  disposeListeners = dispose
  return dispose
}

/** 卸载形态监听（测试与 HMR 使用） */
export function uninstallFormFactor(): void {
  disposeListeners?.()
}

export interface UseFormFactorReturn {
  /** 当前形态 */
  formFactor: Readonly<Ref<FormFactor>>
  /** 视口宽（CSS px） */
  width: Readonly<Ref<number>>
  /** 视口高（CSS px） */
  height: Readonly<Ref<number>>
  /** 主输入设备是否可悬停 */
  hasHover: Readonly<Ref<boolean>>
  /** 是否竖屏 */
  isPortrait: Readonly<Ref<boolean>>
  /** 是否手持形态 */
  isHandheld: ComputedRef<boolean>
  /** 是否中屏形态 */
  isMedium: ComputedRef<boolean>
  /** 是否宽屏形态 */
  isWide: ComputedRef<boolean>
  /** 手动刷新一次（测试/极端场景使用） */
  refresh: () => void
}

/**
 * 读取形态状态。可在任意组件内调用，返回的是同一份单例状态。
 */
export function useFormFactor(): UseFormFactorReturn {
  const isHandheld = computed(() => formFactor.value === 'H')
  const isMedium = computed(() => formFactor.value === 'T')
  const isWide = computed(() => formFactor.value === 'W')

  return {
    formFactor: readonly(formFactor),
    width: readonly(width),
    height: readonly(height),
    hasHover: readonly(hasHover),
    isPortrait: readonly(isPortrait),
    isHandheld,
    isMedium,
    isWide,
    refresh,
  }
}
