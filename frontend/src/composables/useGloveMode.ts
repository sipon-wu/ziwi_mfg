/**
 * 手套模式（Glove Mode）
 *
 * 依据：UE §1.2「手套是常态，电容屏会失灵」、§6.1 手套档尺寸、§6.3「手套模式」行、
 *      Q1/Q4 默认建议「手套模式允许设备级记忆、角色默认开启」。
 *
 * 行为：
 * 1. 开关状态按**设备**记忆（localStorage `ziwi:glove-mode`）；
 * 2. 用户没手动设过时，按角色给默认值：操作工 / 仓管 / 设备员 → 默认开启；
 * 3. 结果下发到 `<html data-glove="on|off">`，全站尺寸覆盖只在
 *    `styles/ziwi-tokens.gloves.css` 里发生。
 *
 * 设计取舍：显式用户选择 > 角色默认。即使用户切换了角色，只要他手动关过手套模式，
 * 就尊重他的选择（否则现场"我明明关了又自己开了"会被当成 bug）。
 */
import { computed, readonly, ref, type ComputedRef, type Ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

/** localStorage 键。带 `ziwi:` 前缀，避免与其他应用串味 */
export const GLOVE_STORAGE_KEY = 'ziwi:glove-mode'

/** `<html>` 上的手套属性名（架构 §8.1） */
export const GLOVE_ATTR = 'glove'

/**
 * 默认开启手套模式的角色。
 * 依据 UE §6.3：操作工（operator）/ 仓管（warehouse_keeper）/ 设备员（maintenance_tech）。
 */
export const GLOVE_DEFAULT_ROLES = ['operator', 'warehouse_keeper', 'maintenance_tech'] as const

/** 单例状态 */
const isGlove = ref(false)
/** 是否来自用户显式设置（true 时不再被角色默认值覆盖） */
const isExplicit = ref(false)
/** 是否已初始化，避免重复读存储 */
let initialized = false

function canUseDom(): boolean {
  return typeof window !== 'undefined' && typeof document !== 'undefined'
}

/**
 * 读取设备记忆。
 * @returns `true`/`false` 表示用户显式选择；`null` 表示从未设置过
 */
export function readStoredGloveMode(): boolean | null {
  if (!canUseDom()) return null
  try {
    const raw = window.localStorage.getItem(GLOVE_STORAGE_KEY)
    if (raw === 'on') return true
    if (raw === 'off') return false
    return null
  } catch {
    // 隐私模式 / 存储被禁用
    return null
  }
}

/** 写入设备记忆 */
export function writeStoredGloveMode(enabled: boolean): void {
  if (!canUseDom()) return
  try {
    window.localStorage.setItem(GLOVE_STORAGE_KEY, enabled ? 'on' : 'off')
  } catch {
    // 存储不可用时静默降级：仅本次会话生效
  }
}

/** 把当前状态写到 `<html data-glove>` */
function applyToDocument(enabled: boolean): void {
  if (!canUseDom()) return
  const root = document.documentElement
  const next = enabled ? 'on' : 'off'
  if (root.dataset[GLOVE_ATTR] !== next) {
    root.dataset[GLOVE_ATTR] = next
  }
}

/** 内部设置状态（不写存储），返回是否发生变化 */
function setState(enabled: boolean): boolean {
  const changed = isGlove.value !== enabled
  isGlove.value = enabled
  applyToDocument(enabled)
  return changed
}

/**
 * 根据当前登录用户的角色推断默认档。
 * 未登录 / 无角色时按"不开启"处理（桌面管理员是裸手键盘鼠标用户）。
 */
export function resolveRoleDefault(): boolean {
  try {
    const auth = useAuthStore()
    const roles: unknown = (auth.user as unknown as { roles?: unknown })?.roles
    if (!Array.isArray(roles)) return false
    const codes = roles
      .map((r) => (typeof r === 'string' ? r : (r as { code?: string })?.code))
      .filter((c): c is string => typeof c === 'string' && c.length > 0)
    return codes.some((c) => (GLOVE_DEFAULT_ROLES as readonly string[]).includes(c))
  } catch {
    // Pinia 未安装（单测 / 极端场景）
    return false
  }
}

/**
 * 初始化手套模式。应在 `main.ts` 中、`app.mount()` 之前调用一次。
 *
 * 优先级：设备记忆（显式）> 角色默认 > 关闭。
 *
 * @returns 初始化后的开关值
 */
export function initGloveMode(): boolean {
  const stored = readStoredGloveMode()
  if (stored !== null) {
    isExplicit.value = true
    setState(stored)
  } else {
    isExplicit.value = false
    setState(resolveRoleDefault())
  }
  initialized = true
  return isGlove.value
}

/**
 * 登录/角色变化后重新评估（只在用户从未显式设置过时才跟随角色）。
 */
export function syncGloveModeWithRole(): void {
  if (!initialized) {
    initGloveMode()
    return
  }
  if (isExplicit.value) return
  setState(resolveRoleDefault())
}

export interface UseGloveModeReturn {
  /** 当前是否处于手套模式 */
  isGlove: Readonly<Ref<boolean>>
  /** 是否为用户显式设置（false 表示当前值跟随角色默认） */
  isExplicit: Readonly<Ref<boolean>>
  /** 手套档下最小可点热区（48 / 56），供组件需要算尺寸时读取 */
  touchMin: ComputedRef<string>
  /** 显式设置开关，并写入设备记忆 */
  setGloveMode: (enabled: boolean) => void
  /** 翻转开关 */
  toggleGloveMode: () => void
  /** 清除设备记忆，回到"跟随角色默认" */
  resetGloveMode: () => void
  /** 初始化（幂等） */
  init: () => boolean
}

/**
 * 手套模式 Composable。任意组件可调用，共享同一份单例状态。
 */
export function useGloveMode(): UseGloveModeReturn {
  const touchMin = computed(() => (isGlove.value ? '56px' : '48px'))

  function setGloveMode(enabled: boolean): void {
    isExplicit.value = true
    writeStoredGloveMode(enabled)
    setState(enabled)
  }

  function toggleGloveMode(): void {
    setGloveMode(!isGlove.value)
  }

  function resetGloveMode(): void {
    isExplicit.value = false
    if (canUseDom()) {
      try {
        window.localStorage.removeItem(GLOVE_STORAGE_KEY)
      } catch {
        // 忽略
      }
    }
    setState(resolveRoleDefault())
  }

  return {
    isGlove: readonly(isGlove),
    isExplicit: readonly(isExplicit),
    touchMin,
    setGloveMode,
    toggleGloveMode,
    resetGloveMode,
    init: initGloveMode,
  }
}
