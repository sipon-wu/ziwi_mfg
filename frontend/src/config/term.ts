/**
 * 术语表唯一真源（架构 §8.4，Q5 已拍板）
 *
 * ## 为什么必须集中
 * UI 实测发现同一对象三种叫法混用：`设备 / 设备编码 / 机台`、`维护 / 保养`、
 * `报工管理 / 报工录入`、`备注 / 描述 / 说明`。术语一旦散落，用户会在不同页面
 * 以为是不同东西 —— 车间场景下这直接等价于操作错误。
 *
 * ## 硬规则（静态闸会查）
 * 1. 前端 `.vue` / `.ts` 中 **「维护」字样零命中**（新增代码；T05 批量清理存量）。
 *    统一为「保养」：`保养计划` / `保养任务`。
 * 2. `设备 / 设备编码 / 机台` → 统一「设备」。
 * 3. `报工管理 / 报工录入` → 统一「报工」。
 * 4. `备注 / 描述 / 说明` 按字段语义固定：`remark` → 备注，`description` → 描述，不得互换。
 *
 * ## 用法
 * ```ts
 * import { TERM } from '@/config/term'
 * <h3>{{ TERM.maintenancePlan }}</h3>
 * ```
 * 路由 `meta.title`、菜单文案、页面标题、空态/回执文案都必须取自这里。
 */

/** 术语表（值即最终展示文案） */
export const TERM = {
  /** 保养计划（原「维护计划」） */
  maintenancePlan: '保养计划',
  /** 保养任务（原「维护任务」） */
  maintenanceTask: '保养任务',
  /** 保养记录 */
  maintenanceRecord: '保养记录',
  /** 点检（与保养并列，不可混称） */
  inspection: '点检',
  /** 质量检验（与设备点检区分：检验 = 品质） */
  qualityInspection: '检验',
  /** 报工（原「报工管理」/「报工录入」） */
  workReport: '报工',
  /** 报工单 */
  workReportOrder: '报工单',
  /** 工单 */
  workOrder: '工单',
  /** 设备（原「设备/设备编码/机台」） */
  equipment: '设备',
  /** 设备编码（作为字段标签时） */
  equipmentCode: '设备编码',
  /** 工作中心 */
  workCenter: '工作中心',
  /** 工序 */
  operation: '工序',
  /** 工艺路线 */
  route: '工艺路线',
  /** 库位 */
  warehouseLocation: '库位',
  /** 仓库 */
  warehouse: '仓库',
  /** 批号 */
  batchNo: '批号',
  /** 物料 */
  material: '物料',
  /** 产品 */
  product: '产品',
  /** 出库单 */
  issueOrder: '出库单',
  /** 收货单 */
  receiptOrder: '收货单',
  /** 盘点单 */
  countOrder: '盘点单',
  /** 不合格品评审 */
  ncr: '不合格评审',
  /** 安灯 */
  andon: '安灯',
  /** 试产 */
  trial: '试产',
  /** 备注（对应字段 `remark`） */
  remark: '备注',
  /** 描述（对应字段 `description`） */
  description: '描述',
  /** 说明（对应 `note` / 帮助文本，不是字段） */
  note: '说明',
  /** 数量 */
  qty: '数量',
  /** 状态 */
  status: '状态',
  /** 操作 */
  action: '操作',
  /** 时间 */
  time: '时间',
} as const

export type Term = typeof TERM

/**
 * 术语纠正表：旧叫法 → 新叫法。
 *
 * 用途：
 * 1. T05 批量替换时的对照表（`scripts/check_ui_contract.py` 用它判定违规命中）；
 * 2. 代码评审时人工核对；
 * 3. 迁移期做"旧叫法告警"。
 *
 * 注意：左侧是**待消灭**的字符串，因此本文件是唯一允许出现"维护"二字的地方，
 * 静态闸对本文件做白名单豁免。
 */
export const TERM_LEGACY: ReadonlyArray<{ from: string; to: string; reason: string }> = [
  { from: '维护计划', to: TERM.maintenancePlan, reason: 'UE §8：维护/保养混用，统一为保养' },
  { from: '维护任务', to: TERM.maintenanceTask, reason: 'UE §8：维护/保养混用，统一为保养' },
  { from: '维护记录', to: TERM.maintenanceRecord, reason: 'UE §8：维护/保养混用，统一为保养' },
  { from: '维护中', to: '保养中', reason: 'UE §8：状态文案同步术语' },
  { from: '机台', to: TERM.equipment, reason: 'UE §8：设备/设备编码/机台统一为设备' },
  { from: '报工管理', to: TERM.workReport, reason: 'UE §8：报工管理/报工录入统一为报工' },
  { from: '报工录入', to: TERM.workReport, reason: 'UE §8：报工管理/报工录入统一为报工' },
]

/**
 * 术语替换建议：把一段文案里的旧叫法替换为新叫法。
 *
 * @param input 待处理的文案（标题、菜单名、路由 meta.title）
 * @returns 替换后的文案
 */
export function normalizeTerm(input: string): string {
  if (!input) return input
  return TERM_LEGACY.reduce((acc, item) => acc.split(item.from).join(item.to), input)
}

/**
 * 检测一段文案里是否残留旧叫法。
 *
 * @param input 待检测文案
 * @returns 命中的旧叫法列表（空数组表示干净）
 */
export function findLegacyTerms(input: string): string[] {
  if (!input) return []
  return TERM_LEGACY.filter((item) => input.includes(item.from)).map((item) => item.from)
}
