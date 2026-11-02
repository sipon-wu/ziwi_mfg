/**
 * 草稿保留 + 关闭确认 + 路由离开拦截（UE-16，UE §8「返回行为」、§6.3「误滑关闭」）
 *
 * ## 要解决的问题
 * 现场用户常在填了一半时被叫走 / 锁屏 / 误触返回。现状是 `router.back()` 后
 * **表单内容全丢**，只能重填 —— 这是车间最贵的浪费。
 *
 * ## 三件事
 * 1. **草稿本地保留**：`sessionStorage`（关掉标签页即失效，避免脏数据长期驻留）；
 * 2. **关闭确认**：含未保存内容时，关闭浮层必须二次确认（`confirmDiscard()`）；
 * 3. **路由离开拦截**：`onBeforeRouteLeave` 里判断脏状态。
 *
 * ## 为什么默认 sessionStorage
 * 草稿是"这次操作没做完"，不是"长期收藏"。用 localStorage 会让一个月前的
 * 半成品草稿在某天突然冒出来，用户会以为数据被污染。
 */
import {
  computed,
  getCurrentInstance,
  onBeforeUnmount,
  ref,
  type ComputedRef,
  type Ref,
} from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

/** 存储前缀，避免与其他键冲突 */
const STORAGE_PREFIX = 'ziwi:draft:'

/** 草稿结构 */
export interface DraftPayload<T = Record<string, unknown>> {
  /** 业务键（同一表单用同一 key，如 `wms:issue-order:new`） */
  key: string
  /** 保存时间（ISO） */
  savedAt: string
  /** 表单快照 */
  data: T
}

/** 存储后端 */
export type DraftStorage = 'session' | 'local'

export interface UseDirtyGuardOptions<T = Record<string, unknown>> {
  /** 草稿键，必须全局唯一（建议 `{模块}:{实体}:{场景}`） */
  key: string
  /** 取当前表单快照（仅在需要保存/比较时调用） */
  snapshot: () => T
  /** 是否有未保存改动。缺省为"快照与上次保存点不同" */
  isDirty?: () => boolean
  /** 恢复草稿时回调（组件用它回填表单） */
  onRestore?: (data: T, savedAt: string) => void
  /** 存储后端，默认 session */
  storage?: DraftStorage
  /** 是否自动注册路由离开守卫（默认 true，且只在 setup 内有效） */
  autoRouteGuard?: boolean
  /** 离开确认文案 */
  confirmMessage?: () => string
}

export interface UseDirtyGuardReturn<T = Record<string, unknown>> {
  /** 当前是否有未保存内容 */
  isDirty: ComputedRef<boolean>
  /** 本地是否存有草稿 */
  hasDraft: Ref<boolean>
  /** 草稿保存时间（无草稿为 null） */
  draftSavedAt: Ref<string | null>
  /** 手动标记"已保存"（保存成功后调用，之后不再是脏的） */
  markClean: () => void
  /** 手动标记"已改动" */
  markDirty: () => void
  /** 保存草稿到本地，返回是否成功 */
  saveDraft: () => boolean
  /** 读取草稿（不自动恢复） */
  readDraft: () => DraftPayload<T> | null
  /** 恢复草稿并回调 onRestore，返回是否恢复到内容 */
  restoreDraft: () => boolean
  /** 清除草稿 */
  clearDraft: () => void
  /**
   * 关闭前调用：有未保存内容时弹确认。
   *
   * @param confirm 确认函数（通常包一层 Vant showDialog），返回 true 表示用户确认放弃
   * @returns 是否允许关闭
   */
  confirmDiscard: (confirm: (message: string) => Promise<boolean>) => Promise<boolean>
  /** 路由离开守卫本体（不自动注册时手动挂） */
  routeGuard: () => boolean
}

/** 计算存储键 */
function storageKey(key: string): string {
  return `${STORAGE_PREFIX}${key}`
}

/** 取存储对象（SSR / 禁用时返回 null） */
function getStorage(kind: DraftStorage): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage
  } catch {
    return null
  }
}

/**
 * 静态读取：不进入组件也能查"有没有草稿"（如列表页的"继续填写"提示）。
 *
 * @param key 草稿键
 * @param storage 存储后端
 */
export function peekDraft<T = Record<string, unknown>>(
  key: string,
  storage: DraftStorage = 'session',
): DraftPayload<T> | null {
  const store = getStorage(storage)
  if (!store) return null
  try {
    const raw = store.getItem(storageKey(key))
    if (!raw) return null
    const parsed = JSON.parse(raw) as DraftPayload<T>
    if (!parsed || typeof parsed !== 'object' || !('data' in parsed)) return null
    return parsed
  } catch {
    return null
  }
}

/**
 * 静态清除草稿（保存成功后即调用，无需组件上下文）。
 *
 * @param key 草稿键
 * @param storage 存储后端
 */
export function dropDraft(key: string, storage: DraftStorage = 'session'): void {
  const store = getStorage(storage)
  if (!store) return
  try {
    store.removeItem(storageKey(key))
  } catch {
    // 忽略：存储不可用等于没有草稿
  }
}

/**
 * 草稿守卫 Composable。
 *
 * @param options 见 {@link UseDirtyGuardOptions}
 */
export function useDirtyGuard<T = Record<string, unknown>>(
  options: UseDirtyGuardOptions<T>,
): UseDirtyGuardReturn<T> {
  const { key, snapshot, storage = 'session' } = options

  const dirty = ref(false)
  const draftSavedAt = ref<string | null>(peekDraft<T>(key, storage)?.savedAt ?? null)
  const hasDraft = ref(draftSavedAt.value !== null)

  const isDirty = computed(() => dirty.value)

  function markClean(): void {
    dirty.value = false
  }

  function markDirty(): void {
    dirty.value = true
  }

  function isDirtyNow(): boolean {
    if (typeof options.isDirty === 'function') return options.isDirty()
    return dirty.value
  }

  function saveDraft(): boolean {
    const store = getStorage(storage)
    if (!store) return false
    const payload: DraftPayload<T> = {
      key,
      savedAt: new Date().toISOString(),
      data: snapshot(),
    }
    try {
      store.setItem(storageKey(key), JSON.stringify(payload))
      draftSavedAt.value = payload.savedAt
      hasDraft.value = true
      return true
    } catch {
      // 配额超限 / 隐私模式
      return false
    }
  }

  function readDraft(): DraftPayload<T> | null {
    return peekDraft<T>(key, storage)
  }

  function restoreDraft(): boolean {
    const payload = readDraft()
    if (!payload) {
      hasDraft.value = false
      draftSavedAt.value = null
      return false
    }
    hasDraft.value = true
    draftSavedAt.value = payload.savedAt
    markClean()
    options.onRestore?.(payload.data, payload.savedAt)
    return true
  }

  function clearDraft(): void {
    dropDraft(key, storage)
    draftSavedAt.value = null
    hasDraft.value = false
    markClean()
  }

  async function confirmDiscard(
    confirm: (message: string) => Promise<boolean>,
  ): Promise<boolean> {
    if (!isDirtyNow()) return true
    const message =
      options.confirmMessage?.() ?? '当前内容还没保存，离开后会丢失，确定离开？'
    return await confirm(message)
  }

  function routeGuard(): boolean {
    if (!isDirtyNow()) return true
    const message =
      options.confirmMessage?.() ?? '当前内容还没保存，离开后会丢失，确定离开？'
    // 交给浏览器/路由层弹确认：vue-router 里返回 false 会中止导航
    if (typeof window !== 'undefined' && typeof window.confirm === 'function') {
      return window.confirm(message)
    }
    return true
  }

  // 仅在 setup 上下文内自动挂路由守卫（在 setup 外调用 getCurrentInstance 返回 null）
  const instance = getCurrentInstance()
  if (options.autoRouteGuard !== false && instance) {
    onBeforeRouteLeave(() => routeGuard())
    onBeforeUnmount(() => {
      // 组件卸载不算"保存"，草稿已经在本地，不做任何清理
    })
  }

  return {
    isDirty,
    hasDraft,
    draftSavedAt,
    markClean,
    markDirty,
    saveDraft,
    readDraft,
    restoreDraft,
    clearDraft,
    confirmDiscard,
    routeGuard,
  }
}
