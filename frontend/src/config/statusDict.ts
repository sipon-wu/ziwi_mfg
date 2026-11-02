/**
 * 状态字典唯一真源（架构 §8.2）
 *
 * ## 为什么必须集中
 * 现状 24 个页面各写一份 `statusLabel` / `statusColor` / `RESULT_MAP`，
 * 改一处漏九处；更严重的是**同一状态码在不同页面被译成不同文字**（UE §8「状态标签」行）。
 *
 * ## 双编码（UE §1.2 / §3.2，硬要求）
 * 状态不能只靠颜色表达 —— 车间强光、反光、色弱都让纯色块失效。因此每条记录必须同时给出：
 * - `label` 文字（颜色之外的第一重编码）
 * - `icon`  图标（第二重编码，形状层面可分）
 * - `semantic` 语义档 → 映射到 CSS `--ziwi-state-{semantic}-*` 的颜色（第三重）
 *
 * 缺任一半即为违规；`scripts/check_ui_contract.py` 会断言本文件的每条记录都有
 * 非空 `label` 与 `icon`。
 *
 * ## 规则
 * 1. 状态码 **原样使用后端值**，前端不得翻译/派生（架构 §8.1）。
 * 2. 新增一个状态码 = **只改这一个文件**。
 * 3. 页面内出现 `const statusLabel = {}` / `RESULT_MAP` / `statusColor` 即违规。
 * 4. 渲染必须走 `useStatusTag(domain, code)`，组件强制同时渲染 icon + label。
 *
 * T01 只建立字典与取值函数，**不改任何页面**（页面切换在 T05 批量做）。
 */

/** 五个语义档。对应 CSS `--ziwi-state-{semantic}-{fg|bg|bd}`，见 styles/ziwi-tokens.css */
export type StateSemantic = 'neutral' | 'progress' | 'success' | 'warning' | 'danger'

/** 一条状态记录 */
export interface StateEntry {
  /** 面向用户的文案（必须与后端语义一致，禁止自造近义词） */
  label: string
  /** 语义档 → 决定颜色 */
  semantic: StateSemantic
  /** 图标名（Vant icon name）。双编码的"形状"一半，禁止为空 */
  icon: string
  /** 排序权重，越小越靠前。列表默认"待处理优先"（UE §8「列表默认排序」） */
  order: number
  /** 是否需要用户立即处理。用于列表高亮与"待办"统计 */
  actionable?: boolean
}

/** Vant 图标名常量，避免各文件写字面量拼错 */
const ICON = {
  clock: 'clock-o',
  play: 'play-circle-o',
  check: 'passed',
  close: 'close',
  warning: 'warning-o',
  info: 'info-o',
  pause: 'pause-circle-o',
  edit: 'edit',
  lock: 'lock',
  cart: 'cart-o',
  todo: 'todo-list-o',
  repair: 'setting-o',
  bolt: 'lightning-o',
  question: 'question-o',
} as const

/**
 * 状态字典。外层 key 是 domain，内层 key 是后端状态码。
 *
 * domain 命名口径：`{模块}_{实体}`，与后端表名一一对应，便于 T03/T04 按 code 集合写判据。
 */
export const STATUS_DICT: Record<string, Record<string, StateEntry>> = {
  // ── 仓储 · 出库单（WMS §3.3 需新增接口的那条路径）──
  wms_issue: {
    pending: { label: '待出库', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    picking: { label: '拣货中', semantic: 'progress', icon: ICON.cart, order: 20, actionable: true },
    partially_issued: { label: '部分出库', semantic: 'warning', icon: ICON.warning, order: 30, actionable: true },
    issued: { label: '已完成', semantic: 'success', icon: ICON.check, order: 40 },
    cancelled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 90 },
  },

  // ── 仓储 · 收货单 ──
  wms_receipt: {
    pending: { label: '待收货', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    inspecting: { label: '待检', semantic: 'progress', icon: ICON.clock, order: 20, actionable: true },
    partially_stored: { label: '部分上架', semantic: 'warning', icon: ICON.warning, order: 30, actionable: true },
    stored: { label: '已完成', semantic: 'success', icon: ICON.check, order: 40 },
    cancelled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 90 },
  },

  // ── 仓储 · 库存预警 ──
  wms_alert: {
    open: { label: '未处理', semantic: 'danger', icon: ICON.warning, order: 10, actionable: true },
    acknowledged: { label: '已确认', semantic: 'warning', icon: ICON.info, order: 20, actionable: true },
    resolved: { label: '已解决', semantic: 'success', icon: ICON.check, order: 40 },
  },

  // ── 仓储 · 批次 ──
  wms_batch: {
    active: { label: '正常', semantic: 'success', icon: ICON.check, order: 10 },
    locked: { label: '锁定', semantic: 'danger', icon: ICON.lock, order: 20, actionable: true },
    expired: { label: '过期', semantic: 'warning', icon: ICON.clock, order: 30, actionable: true },
    blocked: { label: '冻结', semantic: 'neutral', icon: ICON.pause, order: 40, actionable: true },
  },

  // ── 仓储 · 盘点单 ──
  wms_count: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 10 },
    in_progress: { label: '盘点中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    completed: { label: '已完成', semantic: 'success', icon: ICON.check, order: 30 },
    adjusted: { label: '已调整', semantic: 'warning', icon: ICON.edit, order: 40 },
    closed: { label: '已关闭', semantic: 'neutral', icon: ICON.lock, order: 90 },
  },

  // ── 设备（TPM）· 保养任务 ──
  maintenance_task: {
    pending: { label: '待执行', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    in_progress: { label: '执行中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    completed: { label: '已完成', semantic: 'success', icon: ICON.check, order: 30 },
    // 后端历史数据同时存在 canceled / cancelled 两种拼写，两者都收，避免页面各自兜底
    canceled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 90 },
    cancelled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 90 },
  },

  // ── 设备（TPM）· 保养计划（T02 新增：页面不再自建 statusLabels）──
  maintenance_plan: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 5 },
    active: { label: '已启用', semantic: 'success', icon: ICON.check, order: 10 },
    paused: { label: '已暂停', semantic: 'warning', icon: ICON.pause, order: 20, actionable: true },
    archived: { label: '已归档', semantic: 'neutral', icon: ICON.lock, order: 90 },
  },

  // ── 设备（TPM）· 保养项判定（逐项三态）──
  maintenance_item: {
    normal: { label: '正常', semantic: 'success', icon: ICON.check, order: 10 },
    abnormal: { label: '异常', semantic: 'danger', icon: ICON.warning, order: 20, actionable: true },
    na: { label: '不适用', semantic: 'neutral', icon: ICON.question, order: 30 },
    // 未判定的空态（项级还没点）
    '': { label: '未点检', semantic: 'neutral', icon: ICON.clock, order: 0, actionable: true },
  },

  // ── 品质 · 检验单判定 ──
  inspection_order: {
    '': { label: '待判定', semantic: 'neutral', icon: ICON.clock, order: 0, actionable: true },
    pending: { label: '待判定', semantic: 'neutral', icon: ICON.clock, order: 0, actionable: true },
    ACC: { label: '合格', semantic: 'success', icon: ICON.check, order: 10 },
    REJ: { label: '不合格', semantic: 'danger', icon: ICON.close, order: 20, actionable: true },
    UAI: { label: '待判定', semantic: 'warning', icon: ICON.question, order: 30, actionable: true },
  },

  // ── 品质 · 单条检验结果 ──
  inspection_result: {
    PASS: { label: '合格', semantic: 'success', icon: ICON.check, order: 10 },
    FAIL: { label: '不合格', semantic: 'danger', icon: ICON.close, order: 20, actionable: true },
  },

  // ── 设备台账状态 ──
  equipment: {
    running: { label: '运行中', semantic: 'success', icon: ICON.play, order: 10 },
    idle: { label: '空闲', semantic: 'neutral', icon: ICON.pause, order: 20 },
    maintenance: { label: '保养中', semantic: 'progress', icon: ICON.repair, order: 30, actionable: true },
    fault: { label: '故障', semantic: 'danger', icon: ICON.bolt, order: 5, actionable: true },
    scrapped: { label: '已报废', semantic: 'neutral', icon: ICON.close, order: 90 },
  },

  // ── 基础数据 · 工艺路线 ──
  route: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 10, actionable: true },
    published: { label: '已发布', semantic: 'success', icon: ICON.check, order: 20 },
    archived: { label: '已归档', semantic: 'neutral', icon: ICON.lock, order: 90 },
  },

  // ── 生产 · 工单 ──
  work_order: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 50 },
    released: { label: '已下达', semantic: 'progress', icon: ICON.todo, order: 10, actionable: true },
    in_progress: { label: '生产中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    completed: { label: '已完工', semantic: 'success', icon: ICON.check, order: 30 },
    closed: { label: '已关闭', semantic: 'neutral', icon: ICON.lock, order: 90 },
    cancelled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 95 },
  },
}

/** 未知状态码的兜底记录：把原码原样显示出来（绝不吞掉信息） */
export function fallbackEntry(code: string): StateEntry {
  const raw = code === '' || code === null || code === undefined ? '未设置' : String(code)
  return {
    label: raw,
    semantic: 'neutral',
    icon: ICON.info,
    order: 999,
  }
}

/**
 * 取一条状态记录。
 *
 * @param domain 字典域（如 `wms_issue`）
 * @param code 后端状态码（原样传入，空串也是合法码）
 * @returns 状态记录；domain 未知或 code 未登记时返回兜底记录
 */
export function getStateEntry(domain: string, code: string | null | undefined): StateEntry {
  const group = STATUS_DICT[domain]
  if (!group) return fallbackEntry(code ?? '')
  const key = code === null || code === undefined ? '' : String(code)
  return group[key] ?? fallbackEntry(key)
}

/** 列出某 domain 的全部状态码（供筛选下拉、图例使用） */
export function listStatusCodes(domain: string): string[] {
  const group = STATUS_DICT[domain]
  if (!group) return []
  return Object.keys(group)
}

/** 全部 domain 名（供静态闸与文档生成使用） */
export function listStatusDomains(): string[] {
  return Object.keys(STATUS_DICT)
}
