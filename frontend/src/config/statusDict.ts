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
  // ⚠️ `paused` 必须在这里：`WorkOrderList` / `WorkOrderDetail` 的本地 map 有它，
  //    中央字典曾漏掉 —— 页面一旦改用中央字典，「已暂停」就会退化成英文 `paused`。
  work_order: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 50 },
    released: { label: '已下达', semantic: 'progress', icon: ICON.todo, order: 10, actionable: true },
    in_progress: { label: '生产中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    paused: { label: '已暂停', semantic: 'warning', icon: ICON.pause, order: 25, actionable: true },
    completed: { label: '已完工', semantic: 'success', icon: ICON.check, order: 30 },
    closed: { label: '已关闭', semantic: 'neutral', icon: ICON.lock, order: 90 },
    cancelled: { label: '已作废', semantic: 'danger', icon: ICON.close, order: 95 },
  },

  // ── 生产 · 齐套检查 ──
  kitting: {
    pending: { label: '未检查', semantic: 'neutral', icon: ICON.clock, order: 10, actionable: true },
    passed: { label: '齐套通过', semantic: 'success', icon: ICON.check, order: 20 },
    force_passed: { label: '强制放行', semantic: 'warning', icon: ICON.warning, order: 30, actionable: true },
    failed: { label: '缺料', semantic: 'danger', icon: ICON.close, order: 5, actionable: true },
    no_bom: { label: '未配置 BOM', semantic: 'neutral', icon: ICON.question, order: 40 },
  },

  // ── 生产 · 报工单 ──
  work_report: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 50 },
    submitted: { label: '已提交', semantic: 'progress', icon: ICON.todo, order: 10, actionable: true },
    approved: { label: '已审核', semantic: 'success', icon: ICON.check, order: 20 },
    rejected: { label: '已驳回', semantic: 'danger', icon: ICON.close, order: 30, actionable: true },
  },

  // ── 生产 · 工序任务（work_order_steps）──
  // ★ 只有三个状态，与后端 `constants/work_order_states.py::STEP_STATUSES` 一致。
  //   刻意没有「阻塞」：阻塞与缺料是**工单侧**在查询时推出来的动态标记
  //   （`blocked` / `material_check_status`），不是工序自身状态。
  //   把它做成状态码，就得有人在安灯解除时负责改回来 —— 没人负责的字段
  //   迟早长期卡在阻塞，现场见几次假的就不再信它。
  work_order_step: {
    pending: { label: '待作业', semantic: 'neutral', icon: ICON.clock, order: 10, actionable: true },
    in_progress: { label: '作业中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    completed: { label: '已完工', semantic: 'success', icon: ICON.check, order: 30 },
  },

  // ── 品质 · 不合格评审 NCR ──
  // 后端模型注释写 `open/in_progress/completed/verified`，实际库里有
  // `open/reviewing/disposed/closed/cancelled` —— 两套都收，避免任何一边露英文。
  ncr: {
    open: { label: '待评审', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    reviewing: { label: '评审中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    in_progress: { label: '评审中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    disposed: { label: '已处置', semantic: 'progress', icon: ICON.check, order: 30 },
    completed: { label: '已处置', semantic: 'progress', icon: ICON.check, order: 30 },
    verified: { label: '已验证', semantic: 'success', icon: ICON.check, order: 40 },
    closed: { label: '已关闭', semantic: 'neutral', icon: ICON.lock, order: 90 },
    cancelled: { label: '已作废', semantic: 'danger', icon: ICON.close, order: 95 },
  },

  // ── 品质 · FMEA 文档 ──
  fmea: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 10, actionable: true },
    published: { label: '已发布', semantic: 'success', icon: ICON.check, order: 20 },
    revised: { label: '修订中', semantic: 'progress', icon: ICON.edit, order: 25, actionable: true },
    active: { label: '已生效', semantic: 'success', icon: ICON.check, order: 20 },
    obsolete: { label: '已作废', semantic: 'neutral', icon: ICON.close, order: 90 },
    archived: { label: '已归档', semantic: 'neutral', icon: ICON.lock, order: 95 },
  },

  // ── 品质 · FMEA 整改措施 ──
  fmea_action: {
    open: { label: '待处理', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    in_progress: { label: '进行中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    completed: { label: '已完成', semantic: 'success', icon: ICON.check, order: 30 },
    closed: { label: '已关闭', semantic: 'neutral', icon: ICON.lock, order: 90 },
  },

  // ── 品质 · 控制计划 ──
  control_plan: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 10, actionable: true },
    published: { label: '已发布', semantic: 'success', icon: ICON.check, order: 20 },
    revising: { label: '修订中', semantic: 'progress', icon: ICON.edit, order: 25, actionable: true },
    active: { label: '已启用', semantic: 'success', icon: ICON.check, order: 20 },
    archived: { label: '已归档', semantic: 'neutral', icon: ICON.lock, order: 90 },
  },

  // ── 品质 · PPAP 提交 ──
  ppap_submission: {
    draft: { label: '草稿', semantic: 'neutral', icon: ICON.edit, order: 10, actionable: true },
    submitted: { label: '已提交', semantic: 'progress', icon: ICON.todo, order: 20 },
    pending: { label: '待批准', semantic: 'warning', icon: ICON.clock, order: 25, actionable: true },
    approved: { label: '已批准', semantic: 'success', icon: ICON.check, order: 30 },
    conditional: { label: '有条件批准', semantic: 'warning', icon: ICON.warning, order: 35, actionable: true },
    rejected: { label: '已拒绝', semantic: 'danger', icon: ICON.close, order: 5, actionable: true },
  },

  // ── 品质 · PPAP 要素（逐项的提交状态）──
  // 后端模型声明 not_started/in_progress/completed/not_applicable，
  // 而页面按 upload 语义写了 pending/completed 两个值 —— 并集都收。
  ppap_element: {
    not_started: { label: '未开始', semantic: 'neutral', icon: ICON.clock, order: 10, actionable: true },
    pending: { label: '待处理', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    in_progress: { label: '进行中', semantic: 'progress', icon: ICON.play, order: 20, actionable: true },
    completed: { label: '已上传', semantic: 'success', icon: ICON.check, order: 30 },
    rejected: { label: '已退回', semantic: 'danger', icon: ICON.close, order: 5, actionable: true },
    not_applicable: { label: '不适用', semantic: 'neutral', icon: ICON.question, order: 40 },
  },

  // ── 试产单 ──
  trial: {
    planning: { label: '规划', semantic: 'neutral', icon: ICON.edit, order: 10, actionable: true },
    lab_trial: { label: '小试', semantic: 'progress', icon: ICON.clock, order: 20, actionable: true },
    pilot_run: { label: '中试', semantic: 'progress', icon: ICON.play, order: 30, actionable: true },
    batch_verify: { label: '小批量验证', semantic: 'progress', icon: ICON.play, order: 40, actionable: true },
    review: { label: '评审', semantic: 'warning', icon: ICON.todo, order: 50, actionable: true },
    production: { label: '转量产', semantic: 'success', icon: ICON.check, order: 60 },
    terminated: { label: '已终止', semantic: 'danger', icon: ICON.close, order: 90 },
  },

  // ── 安灯呼叫 ──
  andon_call: {
    pending: { label: '待响应', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    // ★ `open`/`responding` 是**库里真实存在**而模型注释里没有的值（各 3 条 / 1 条）。
    //   早期字典照注释只抄了 acknowledged/in_progress，于是这 4 条安灯在界面上
    //   显示「未知（open）」—— 数据没错，是字典漏了。以库为准补齐。
    open: { label: '待处理', semantic: 'warning', icon: ICON.todo, order: 15, actionable: true },
    acknowledged: { label: '已确认', semantic: 'progress', icon: ICON.info, order: 20, actionable: true },
    in_progress: { label: '响应中', semantic: 'progress', icon: ICON.play, order: 30, actionable: true },
    responding: { label: '响应中', semantic: 'progress', icon: ICON.play, order: 30, actionable: true },
    escalated: { label: '已升级', semantic: 'danger', icon: ICON.bolt, order: 35, actionable: true },
    resolved: { label: '已解决', semantic: 'success', icon: ICON.check, order: 50 },
    closed: { label: '已关闭', semantic: 'neutral', icon: ICON.lock, order: 90 },
    cancelled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 95 },
  },

  // ── 能碳 · 计量设备（M11）──
  energy_device: {
    online: { label: '在线', semantic: 'success', icon: ICON.check, order: 10 },
    offline: { label: '离线', semantic: 'neutral', icon: ICON.pause, order: 20 },
    fault: { label: '故障', semantic: 'danger', icon: ICON.bolt, order: 5, actionable: true },
    upgrading: { label: '升级中', semantic: 'progress', icon: ICON.repair, order: 30 },
  },

  // ── 实验室委托单 ──
  lab_request: {
    pending: { label: '待接收', semantic: 'warning', icon: ICON.todo, order: 10, actionable: true },
    received: { label: '已接收', semantic: 'progress', icon: ICON.info, order: 20, actionable: true },
    assigned: { label: '已分派', semantic: 'progress', icon: ICON.cart, order: 30, actionable: true },
    in_progress: { label: '进行中', semantic: 'progress', icon: ICON.play, order: 40, actionable: true },
    reviewing: { label: '审核中', semantic: 'warning', icon: ICON.todo, order: 50, actionable: true },
    done: { label: '已完成', semantic: 'success', icon: ICON.check, order: 60 },
    completed: { label: '已完成', semantic: 'success', icon: ICON.check, order: 60 },
    canceled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 90 },
    cancelled: { label: '已取消', semantic: 'danger', icon: ICON.close, order: 90 },
  },
}

/** 未知状态码的兜底记录：显式标出「未知（原码）」，绝不把脏值伪装成正常值 */
export function fallbackEntry(code: string): StateEntry {
  const empty = code === '' || code === null || code === undefined
  return {
    // ⚠️ 曾经这里直接回显原码，于是 `on_hold` 这种库里没有的脏值
    //    在界面上看起来和 `生产中` 一样正常，谁也发现不了。
    //    中文化检查的目标是"英文原码不该出现在界面上"，所以必须带「未知」前缀。
    label: empty ? '未设置' : `未知（${String(code)}）`,
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
