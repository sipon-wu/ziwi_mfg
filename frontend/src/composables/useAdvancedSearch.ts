/**
 * useAdvancedSearch —— 高级检索条件状态 + 客户端（前端本地）9 算子求值
 *
 * MVP：过滤作用于"当前已加载 items"，零后端改动。多条件 AND 叠加。
 */
import { ref, computed } from 'vue'
import type {
  FieldDef,
  Operator,
  ResourceSearchConfig,
  SearchCondition,
} from '@/types/search'
import { defaultOperatorsFor } from '@/types/search'

let uidSeq = 0
function nextUid(): string {
  uidSeq += 1
  return `c_${uidSeq}_${Date.now().toString(36)}`
}

function isEmptyValue(v: any): boolean {
  return v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)
}

export function useAdvancedSearch<T extends Record<string, any>>(config?: ResourceSearchConfig) {
  const conditions = ref<SearchCondition[]>([])

  /** fieldKey -> FieldDef（合并 searchFields 与 rowDetailFields，便于按类型求值） */
  const fieldMap = computed<Record<string, FieldDef>>(() => {
    const map: Record<string, FieldDef> = {}
    if (config) {
      for (const f of config.searchFields) map[f.key] = f
      for (const f of config.rowDetailFields) if (!map[f.key]) map[f.key] = f
    }
    return map
  })

  const active = computed(() => conditions.value.length > 0)

  function operatorsFor(fieldKey: string): Operator[] {
    const def = fieldMap.value[fieldKey]
    return def?.operators && def.operators.length ? def.operators : defaultOperatorsFor(def?.type || 'string')
  }

  function makeCondition(fieldKey?: string): SearchCondition {
    const key = fieldKey || config?.searchFields[0]?.key || ''
    const op = operatorsFor(key)[0] || 'EQ'
    return { uid: nextUid(), field: key, operator: op, value: undefined, value2: undefined }
  }

  function addCondition(fieldKey?: string): void {
    conditions.value.push(makeCondition(fieldKey))
  }

  function removeCondition(uid: string): void {
    conditions.value = conditions.value.filter((c) => c.uid !== uid)
  }

  function setConditions(next: SearchCondition[]): void {
    conditions.value = next.map((c) => ({ ...c, uid: c.uid || nextUid() }))
  }

  function reset(): void {
    conditions.value = []
  }

  function onFieldChange(cond: SearchCondition): void {
    // 字段变化时，若当前算子对该字段不可用，重置为第一个可用算子
    const ops = operatorsFor(cond.field)
    if (!ops.includes(cond.operator)) {
      cond.operator = ops[0] || 'EQ'
      cond.value = undefined
      cond.value2 = undefined
    }
  }

  // ---------- 9 算子求值 ----------
  function matchOne(item: T, cond: SearchCondition): boolean {
    const def = fieldMap.value[cond.field]
    const raw = (item as any)[cond.field]

    if (cond.operator === 'IS_EMPTY') return isEmptyValue(raw)
    if (cond.operator === 'NOT_EMPTY') return !isEmptyValue(raw)

    if (def?.type === 'number') {
      const a = Number(raw)
      const b = Number(cond.value)
      const b2 = Number(cond.value2)
      if (Number.isNaN(a)) return false
      switch (cond.operator) {
        case 'EQ':
          return a === b
        case 'NEQ':
          return a !== b
        case 'GT':
          return a > b
        case 'LT':
          return a < b
        case 'BETWEEN':
          return a >= b && a <= b2
        default:
          return false
      }
    }

    if (def?.type === 'date') {
      const a = Date.parse(raw)
      const b = Date.parse(cond.value)
      const b2 = Date.parse(cond.value2)
      if (Number.isNaN(a)) return false
      switch (cond.operator) {
        case 'EQ':
          return !Number.isNaN(b) && sameDay(a, b)
        case 'GT':
          return !Number.isNaN(b) && a > b
        case 'LT':
          return !Number.isNaN(b) && a < b
        case 'BETWEEN':
          return !Number.isNaN(b) && !Number.isNaN(b2) && a >= b && a <= b2
        default:
          return false
      }
    }

    if (def?.type === 'boolean') {
      const a = raw === true || raw === 'true' || raw === 1 || raw === '1'
      const b = cond.value === true || cond.value === 'true' || cond.value === 1 || cond.value === '1'
      return cond.operator === 'EQ' ? a === b : true
    }

    // string / enum
    const sa = String(raw ?? '')
    const sb = String(cond.value ?? '')
    switch (cond.operator) {
      case 'EQ':
        return sa === sb
      case 'NEQ':
        return sa !== sb
      case 'CONTAINS':
        return sa.includes(sb)
      case 'NOT_CONTAINS':
        return !sa.includes(sb)
      default:
        return false
    }
  }

  function sameDay(a: number, b: number): boolean {
    const da = new Date(a)
    const db = new Date(b)
    return (
      da.getFullYear() === db.getFullYear() &&
      da.getMonth() === db.getMonth() &&
      da.getDate() === db.getDate()
    )
  }

  /** 对传入数组按当前条件本地过滤，返回新数组（AND 叠加） */
  function applyFilter(items: T[]): T[] {
    if (conditions.value.length === 0) return items
    return items.filter((item) => conditions.value.every((c) => matchOne(item, c)))
  }

  return {
    conditions,
    active,
    addCondition,
    removeCondition,
    setConditions,
    reset,
    onFieldChange,
    applyFilter,
  }
}
