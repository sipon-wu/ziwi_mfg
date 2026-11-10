/**
 * 扫码输入聚合（架构 §5.1 / UE §2.5「扫码优先于选择」）
 *
 * ## 三通道
 * 1. **物理扫描键（硬键）**：扫码枪本质是键盘，会在极短时间内"逐字符键入 + Enter"。
 *    因此判定条件是**连续字符 + Enter**：相邻字符间隔 ≤ {@link DEFAULT_MAX_INTERVAL}ms
 *    且长度 ≥ {@link SCAN_MIN_LENGTH}，收到 Enter 即一次性吐出整串。
 * 2. **软扫**：页面内相机/系统扫码头把结果 `set` 进来，走 `handleInput`。
 * 3. **粘贴兜底**：用户从别处复制编码粘贴，走 `handlePaste`（粘贴的间隔为 0，
 *    天然满足"连续字符"，但可能没有 Enter，所以粘贴直接成码）。
 *
 * ## 为什么不用"检测 keypress 间隔 < 30ms"这类硬编码
 * 不同扫码枪的键入间隔从 5ms 到 80ms 都有，且会受浏览器节流影响。因此上限取
 * 宽容值（120ms 默认），同时要求 Enter 收尾 —— 人手连续打字很难在 120ms 内打出
 * 8 个以上字符再按 Enter，误触概率极低。
 *
 * ## 防抖
 * 软扫通道（`handleInput`）没有 Enter 事件，只能靠防抖收口：最后一次输入后
 * 静置 `debounceMs` 即视为一次完整扫描。
 *
 * ## ★ Enter 以「输入框当前值」为准，不以内部缓冲为准（2026-11-10 修）
 * 扫码枪本质是键盘 —— **扫码和手工录入在浏览器里是同一件事**，区别只是敲得快。
 * 所以回车时该提交的是"框里现在是什么"，而不是"我猜这是不是一次扫描"。
 *
 * 此前 `Enter` 只看内部缓冲：慢速手输时相邻字符间隔 > `maxInterval`，
 * 缓冲被重置成最后一个字符，回车时长度不够 → 静默清空、**什么都不发生**。
 * 而扫码枪（30ms/字符）能过 → 现场表现成"扫码能查、手输查不了，必须多点一次按钮"。
 * 更糟的是中等速度会留下 `003749` 这种**后缀**：长度够了就当完整码提交，
 * 查出来的是另一个码或直接查无此码，而界面上看不出发生过替换。
 *
 * 现在缓冲只负责两件事：`isScanning` 的"正在识别…"视觉、以及页面级全局监听
 * （`global: true`，此时没有输入框可读）。**成码内容一律以调用方给的
 * `currentValue` 为准**，没给才退回缓冲。
 */
import { onBeforeUnmount, readonly, ref, type Ref } from 'vue'

/** 相邻字符最大间隔（ms）。超过即认为是人在打字，重置缓冲 */
export const DEFAULT_MAX_INTERVAL = 120

/**
 * 一次有效扫码的**最小长度**。太短无法区分"手输两三个字符"与"扫码"。
 *
 * ★ **单一真源**：`ZiwiScanField` 的回车判定与「扫码」按钮兜底都取它，
 *   不要再在组件里手写 `3` / 或依赖 composable 的另一份默认值 —— 此前是
 *   组件传 3、composable 默认 4，两处取值并存，改一处另一处不变。
 *
 * 为什么是 3 而不是更长：真实业务码（批次码最短 9 位、工单号最短 10 位）
 * 都远长于它，这个阈值只负责**挡住误触回车/两三个字的手输**，不是业务校验。
 * 取 3 是与现网行为一致的最小改动；真要做业务级长度校验，应该在具体页面的
 * `@scan` 处理里对着真实码规则校验，而不是把这个全局阈值调大。
 */
export const SCAN_MIN_LENGTH = 3

/** 软扫/粘贴的收口防抖时长（ms） */
export const DEFAULT_DEBOUNCE_MS = 160

export interface UseScanInputOptions {
  /**
   * 收到一次完整扫码时回调。
   * 返回 `false` 表示"这次不算"，不会清空输入框（用于业务校验失败时保留原码）。
   */
  onScan: (code: string) => void | boolean | Promise<void | boolean>
  /** 最小长度，默认 {@link SCAN_MIN_LENGTH}；页面有更严的码规则时在 `@scan` 里校验 */
  minLength?: number
  /** 相邻字符最大间隔，默认 120ms */
  maxInterval?: number
  /** 软扫防抖，默认 160ms */
  debounceMs?: number
  /** 是否在扫码成功后自动清空缓冲，默认 true */
  clearOnScan?: boolean
  /** 是否在 document 上全局监听键盘（页面级扫码入口用），默认 false */
  global?: boolean
}

export interface UseScanInputReturn {
  /** 当前聚合缓冲（可用于展示"正在识别…"） */
  buffer: Ref<string>
  /** 是否已识别为"正在扫"（连续字符超过阈值） */
  isScanning: Ref<boolean>
  /** 上一次成功成码的来源（硬键 / 粘贴 / 软扫），可用于埋点或差异化提示 */
  lastSource: Readonly<Ref<ScanSource>>
  /** 键盘事件处理器，绑到输入框或 document */
  handleKeydown: (event: KeyboardEvent, currentValue?: string) => void
  /** 粘贴处理器 */
  handlePaste: (event: ClipboardEvent) => void
  /** 软扫 / 手输兜底：把当前输入框的值交给它 */
  handleInput: (value: string) => void
  /** 立即把缓冲当作一次扫码吐出去（不满足长度则丢弃） */
  flush: (reason?: ScanSource) => Promise<boolean>
  /** 清空缓冲 */
  reset: () => void
  /** 手动解除全局监听（global 模式下提前收尾用） */
  dispose: () => void
}

/** 扫码来源标记，便于业务侧区分（硬键扫/粘贴/软扫） */
export type ScanSource = 'keyboard' | 'paste' | 'input'

/**
 * 扫码输入 Composable。
 *
 * @param options 见 {@link UseScanInputOptions}
 */
export function useScanInput(options: UseScanInputOptions): UseScanInputReturn {
  const minLength = options.minLength ?? SCAN_MIN_LENGTH
  const maxInterval = options.maxInterval ?? DEFAULT_MAX_INTERVAL
  const debounceMs = options.debounceMs ?? DEFAULT_DEBOUNCE_MS
  const clearOnScan = options.clearOnScan !== false

  const buffer = ref('')
  const isScanning = ref(false)
  /** 上一次成功成码的来源 */
  const lastSource = ref<ScanSource>('keyboard')

  /** 上一次按键时间戳 */
  let lastKeyAt = 0
  /** 软扫防抖句柄 */
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  /** 全局监听解绑函数 */
  let disposeGlobal: (() => void) | null = null

  function clearDebounce(): void {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
  }

  function reset(): void {
    buffer.value = ''
    isScanning.value = false
    lastKeyAt = 0
    clearDebounce()
  }

  /**
   * 把缓冲提交出去。
   *
   * @param source 来源标记（硬键 / 粘贴 / 软扫），仅用于日志与埋点
   * @param rawValue 成码内容。**给了就用它**（输入框当前值），不给才退回内部缓冲
   * @returns 是否成功吐出一码
   */
  async function flush(source: ScanSource = 'keyboard', rawValue?: string): Promise<boolean> {
    clearDebounce()
    const code = (rawValue ?? buffer.value).trim()
    if (code.length < minLength) {
      // 达不到扫码特征：当成普通输入，不清空（用户可能只是手输了几个字）
      isScanning.value = false
      return false
    }

    let accepted: void | boolean = true
    try {
      accepted = await options.onScan(code)
    } finally {
      // 无论成败都要退出"识别中"，否则界面会卡在扫描态
      isScanning.value = false
    }

    const shouldClear = accepted !== false && clearOnScan
    if (shouldClear) {
      buffer.value = ''
    } else {
      // 业务校验失败时保留原码，方便用户核对
      buffer.value = code
    }
    lastSource.value = source
    return accepted !== false
  }

  /**
   * @param event 键盘事件
   * @param currentValue **输入框当前值**。有输入框的场景必须传 —— 回车以它为准，
   *   否则慢速手输会被内部缓冲的"重置"逻辑吞掉（见文件头注释）
   */
  function handleKeydown(event: KeyboardEvent, currentValue?: string): void {
    // 只处理可打印键与 Enter；忽略组合键（Ctrl+V 走 paste 通道）
    if (event.ctrlKey || event.metaKey || event.altKey) return

    if (event.key === 'Enter') {
      // ★ 先看框里有什么，再看缓冲。扫码枪和真人手输走同一条判定，
      //   唯一区别是扫码枪能让缓冲也满 —— 但那只是"识别中"的视觉，不是成码依据。
      const code = (currentValue ?? buffer.value).trim()
      if (code.length >= minLength) {
        // 阻止 Enter 触发外层表单提交
        event.preventDefault()
        void flush('keyboard', code)
      } else {
        // 太短：不提交、也不动输入框里的内容，让人接着打或点扫码按钮
        reset()
      }
      return
    }

    // 单字符键：key 长度为 1 且不是空白
    if (event.key.length !== 1) return
    if (event.key.trim() === '') return

    const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
    const gap = now - lastKeyAt
    lastKeyAt = now

    if (gap > maxInterval) {
      // 间隔过长 → 视为新的一串
      buffer.value = event.key
      isScanning.value = false
    } else {
      buffer.value += event.key
    }

    if (buffer.value.length >= minLength) {
      isScanning.value = true
    }
  }

  function handlePaste(event: ClipboardEvent): void {
    const text = event.clipboardData?.getData('text') ?? ''
    const code = text.trim()
    if (!code) return
    // 粘贴的编码常常带换行/制表符（从 Excel 复制），取第一段
    const first = code.split(/[\r\n\t]/).map((s) => s.trim()).filter(Boolean)[0] ?? ''
    if (first.length < minLength) return
    event.preventDefault()
    buffer.value = first
    void flush('paste')
  }

  function handleInput(value: string): void {
    buffer.value = value ?? ''
    if (buffer.value.length >= minLength) {
      isScanning.value = true
    }
    clearDebounce()
    if (!buffer.value.trim()) {
      isScanning.value = false
      return
    }
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      void flush('input')
    }, debounceMs)
  }

  function dispose(): void {
    clearDebounce()
    disposeGlobal?.()
    disposeGlobal = null
  }

  // 页面级全局监听：物理扫描枪焦点不在输入框时也能被捕获
  if (options.global && typeof document !== 'undefined') {
    const listener = (e: KeyboardEvent): void => handleKeydown(e)
    document.addEventListener('keydown', listener)
    disposeGlobal = () => document.removeEventListener('keydown', listener)
  }

  onBeforeUnmount(() => {
    dispose()
  })

  return {
    buffer,
    isScanning,
    lastSource: readonly(lastSource),
    handleKeydown,
    handlePaste,
    handleInput,
    flush,
    reset,
    dispose,
  }
}
