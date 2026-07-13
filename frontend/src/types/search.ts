/**
 * 知微 ziwi · 高级检索 / 行展开 / 大屏三态 共享类型
 *
 * 仅放本模块新增类型，不触碰 types/index.ts 既有实体。
 */

// ============================================================
// 高级检索 Operator（9 种，全前端统一）
// ============================================================

export type Operator =
  | 'EQ' // 等于
  | 'NEQ' // 不等于
  | 'CONTAINS' // 包含
  | 'NOT_CONTAINS' // 不包含
  | 'GT' // 大于
  | 'LT' // 小于
  | 'BETWEEN' // 区间（取 value + value2）
  | 'IS_EMPTY' // 为空（不取 value）
  | 'NOT_EMPTY' // 不为空（不取 value）

// ============================================================
// 字段定义
// ============================================================

export type FieldType = 'string' | 'number' | 'date' | 'enum' | 'boolean'

/** 字段分组：基础信息 / 关联信息 / 审计信息（用于行展开分组渲染） */
export type FieldGroup = 'basic' | 'relation' | 'audit'

export interface FieldOption {
  label: string
  value: string | number
}

export interface FieldDef {
  key: string
  label: string
  type: FieldType
  /** enum 类型的候选项 */
  options?: FieldOption[]
  /** 该字段支持的算子；留空则按 type 取默认算子 */
  operators?: Operator[]
  /** 行展开时为隐藏字段（created_at/remark/关联 id 等） */
  hidden?: boolean
  /** 行展开分组 */
  group?: FieldGroup
}

// ============================================================
// 检索条件
// ============================================================

export interface SearchCondition {
  /** 行内唯一标识，便于 chips 删除 */
  uid: string
  field: string
  operator: Operator
  /** 单值（EQ/NEQ/CONTAINS/NOT_CONTAINS/GT/LT 取值） */
  value?: any
  /** 区间上界（BETWEEN 取值） */
  value2?: any
}

// ============================================================
// 资源检索配置（按 resource 静态 schema）
// ============================================================

export interface ResourceSearchConfig {
  resource: string
  listEndpoint: string
  detailEndpoint: string
  /** 高级检索可检索字段 */
  searchFields: FieldDef[]
  /** 行展开展示字段（含 hidden:true 的隐藏字段） */
  rowDetailFields: FieldDef[]
}

// ============================================================
// 大屏三态
// ============================================================

export type KpiState = 'loading' | 'real' | 'unavailable'

export interface DashboardKpi {
  key: string
  label: string
  value: number | null
  unit?: string
  state: KpiState
}

export type DashboardModule = {
  code: string
  name: string
  kpis: DashboardKpi[]
}

// ============================================================
// 默认算子（按字段类型）
// ============================================================

export function defaultOperatorsFor(type: FieldType): Operator[] {
  switch (type) {
    case 'string':
      return ['CONTAINS', 'NOT_CONTAINS', 'EQ', 'NEQ', 'IS_EMPTY', 'NOT_EMPTY']
    case 'number':
      return ['EQ', 'NEQ', 'GT', 'LT', 'BETWEEN', 'IS_EMPTY', 'NOT_EMPTY']
    case 'date':
      return ['EQ', 'GT', 'LT', 'BETWEEN', 'IS_EMPTY', 'NOT_EMPTY']
    case 'enum':
      return ['EQ', 'NEQ', 'IS_EMPTY', 'NOT_EMPTY']
    case 'boolean':
      return ['EQ']
    default:
      return ['EQ', 'NEQ', 'CONTAINS', 'IS_EMPTY', 'NOT_EMPTY']
  }
}

/** Operator 中文标签 */
export const OPERATOR_LABELS: Record<Operator, string> = {
  EQ: '等于',
  NEQ: '不等于',
  CONTAINS: '包含',
  NOT_CONTAINS: '不包含',
  GT: '大于',
  LT: '小于',
  BETWEEN: '区间',
  IS_EMPTY: '为空',
  NOT_EMPTY: '不为空',
}
