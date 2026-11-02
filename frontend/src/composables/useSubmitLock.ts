/**
 * 幂等提交锁（UE-P0-05 / UE §6.3「重复提交」）
 *
 * ## 要解决的问题
 * 车间手套 + 油污 = 连点。一次提交在返回前被点 3 次，就会产生 3 个单据。
 * 前端锁**不是唯一防线**（服务端仍需幂等），但它是第一道，且是唯一能立刻生效的一道。
 *
 * ## 语义
 * - `run(key, fn)`：同一个 `key` 在 `fn` 未结束前，后续调用**直接复用同一个 Promise**，
 *   既不重复发请求，也不丢调用方（调用方仍然拿到同一个结果）。
 * - 不同 `key` 互不阻塞（例如"保存草稿"和"提交"可以并行）。
 * - `key` 缺省为 `'default'`，单表单场景不用关心。
 *
 * ## 为什么复用 Promise 而不是"直接 return undefined"
 * 组件里常见写法是 `await lock.run(...)` 然后 toast 成功。如果第二次调用返回 undefined，
 * 调用方会误判失败。复用同一个 Promise 让两次调用的结果完全一致。
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'

/** 全局单例：跨组件共享同一把锁（同一张单据常由页头和底部条各放一个按钮） */
const pending = ref<Map<string, Promise<unknown>>>(new Map())

/** 已完成的提交计数，便于回执页判断"这是第几次" */
const completedCount = ref(0)

/** 默认锁键 */
export const DEFAULT_SUBMIT_KEY = 'default'

/** 提交锁被拒绝时抛出的错误码，便于调用方区分"被锁住"与"业务失败" */
export const SUBMIT_LOCKED = 'ZIWI_SUBMIT_LOCKED'

/** 被锁住的调用拒绝原因 */
export class SubmitLockedError extends Error {
  constructor(key: string) {
    super(`提交正在进行中，请勿重复操作（key=${key}）`)
    this.name = 'SubmitLockedError'
    this.code = SUBMIT_LOCKED
  }

  /** 错误码，便于 `e.code === SUBMIT_LOCKED` 判断 */
  readonly code: string
}

/** 正在提交的锁键集合（响应式，用于按钮 disabled / loading） */
const lockedKeys = ref<Set<string>>(new Set())

export interface UseSubmitLockReturn {
  /** 是否有任意提交在进行中 */
  isSubmitting: ComputedRef<boolean>
  /** 当前进行中的锁键（只读快照） */
  lockedKeys: Readonly<Ref<Set<string>>>
  /** 指定键是否正在提交 */
  isLocked: (key?: string) => boolean
  /**
   * 执行一次幂等提交。
   *
   * @param key 锁键（同一业务动作请用同一个键）
   * @param task 实际提交函数
   * @returns `task` 的返回值；同键并发时复用同一个 Promise
   */
  run: <T>(key: string, task: () => Promise<T>) => Promise<T>
  /** 便捷重载：不关心锁键时直接 `run(fn)` */
  runTask: <T>(task: () => Promise<T>) => Promise<T>
  /** 手动释放某个键（异常恢复用；正常流程由 run 自行释放） */
  release: (key?: string) => void
  /** 全部释放（路由切换/组件卸载时兜底） */
  releaseAll: () => void
  /** 已完成提交次数（只读，单调递增） */
  completedCount: Readonly<Ref<number>>
}

/**
 * 获取提交锁。任意组件可调用，共享同一份单例状态。
 */
export function useSubmitLock(): UseSubmitLockReturn {
  const isSubmitting = computed(() => lockedKeys.value.size > 0)

  function isLocked(key: string = DEFAULT_SUBMIT_KEY): boolean {
    return lockedKeys.value.has(key)
  }

  function release(key: string = DEFAULT_SUBMIT_KEY): void {
    if (!lockedKeys.value.has(key)) return
    const next = new Set(lockedKeys.value)
    next.delete(key)
    lockedKeys.value = next
    pending.value.delete(key)
  }

  function releaseAll(): void {
    lockedKeys.value = new Set()
    pending.value = new Map()
  }

  function run<T>(key: string, task: () => Promise<T>): Promise<T> {
    const lockKey = key || DEFAULT_SUBMIT_KEY
    const existing = pending.value.get(lockKey)
    if (existing) {
      // 同键并发：复用同一个 Promise，绝不二次发请求
      return existing as Promise<T>
    }

    const markLocked = (): void => {
      const next = new Set(lockedKeys.value)
      next.add(lockKey)
      lockedKeys.value = next
    }
    markLocked()

    // 用 Promise.resolve 包裹，保证同步抛错也走 finally
    const promise = Promise.resolve()
      .then(() => task())
      .then(
        (result) => {
          completedCount.value += 1
          return result
        },
        (error) => {
          throw error
        },
      )
      .finally(() => {
        release(lockKey)
      }) as Promise<T>

    pending.value.set(lockKey, promise as Promise<unknown>)
    return promise
  }

  function runTask<T>(task: () => Promise<T>): Promise<T> {
    return run(DEFAULT_SUBMIT_KEY, task)
  }

  return {
    isSubmitting,
    lockedKeys: lockedKeys as Readonly<Ref<Set<string>>>,
    isLocked,
    run,
    runTask,
    release,
    releaseAll,
    completedCount: completedCount as Readonly<Ref<number>>,
  }
}

/**
 * 判断一个错误是否来自提交锁（而不是业务失败）。
 *
 * @param error 捕获到的错误
 */
export function isSubmitLockedError(error: unknown): boolean {
  return (
    error instanceof SubmitLockedError ||
    (typeof error === 'object' && error !== null && (error as { code?: string }).code === SUBMIT_LOCKED)
  )
}
