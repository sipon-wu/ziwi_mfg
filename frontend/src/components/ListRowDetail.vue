<script setup lang="ts">
import { computed } from 'vue'
import type { FieldDef } from '@/types/search'

const props = defineProps<{
  item: Record<string, any>
  fields: FieldDef[]
}>()

/** 可见字段（排除 hidden:true 的字段） */
const visibleFields = computed(() => props.fields.filter((f) => !f.hidden))

/** header 字段数：只统计可见字段，与可见行数一致 */
const visibleCount = computed(() => visibleFields.value.length)

/** 主键摘要：优先取 name/code，否则取第一个非 hidden 字段值 */
const primarySummary = computed(() => {
  const nameVal = props.item?.name
  if (nameVal && String(nameVal).trim()) return String(nameVal)
  const codeVal = props.item?.code
  if (codeVal && String(codeVal).trim()) return String(codeVal)
  const first = visibleFields.value[0]
  if (first) return display(first)
  return '—'
})

function display(f: FieldDef): string {
  const v = props.item[f.key]
  if (v === null || v === undefined || v === '') return '--'
  if (f.type === 'boolean') return v === true || v === 'true' || v === 1 || v === '1' ? '是' : '否'
  if (f.type === 'enum' && f.options) {
    const opt = f.options.find((o) => String(o.value) === String(v))
    return opt ? opt.label : String(v)
  }
  if (f.type === 'date') {
    const s = String(v)
    return s.length >= 10 ? s.slice(0, 10) : s
  }
  if (typeof v === 'object') {
    try {
      return JSON.stringify(v)
    } catch {
      return String(v)
    }
  }
  return String(v)
}
</script>

<template>
  <div class="row-detail">
    <div class="rd-header" v-if="primarySummary">
      <span class="rd-header-summary">{{ primarySummary }}</span>
      <span class="rd-header-count">{{ visibleCount }} 字段</span>
    </div>
    <div class="rd-list">
      <div v-for="f in visibleFields" :key="f.key" class="rd-row">
        <span class="rd-label">{{ f.label }}</span>
        <span class="rd-value" :class="{ 'rd-empty': display(f) === '--' }">
          {{ display(f) }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row-detail {
  padding: 12px 16px 14px;
  background: var(--ziwi-bg-light, #f7f8fa);
  border-top: 1px dashed var(--ziwi-border, #ebedf0);
}

/* ---------- header ---------- */
.rd-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 8px;
  margin-bottom: 4px;
  border-bottom: 0.5px solid var(--ziwi-border, #ebedf0);
  font-size: 13px;
}
.rd-header-summary {
  font-weight: 500;
  color: var(--ziwi-text-primary, #323233);
}
.rd-header-count {
  font-size: 12px;
  color: var(--ziwi-text-muted, #969799);
}

/* ---------- list (per row) ---------- */
.rd-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.rd-row {
  display: flex;
  align-items: baseline;
  padding: 6px 0;
  border-bottom: 0.5px solid var(--ziwi-border, #ebedf0);
  font-size: 13px;
  line-height: 1.5;
}
.rd-row:last-child {
  border-bottom: none;
}

.rd-label {
  color: var(--ziwi-text-muted, #969799);
  font-size: 12px;
  flex-shrink: 0;
  /* label 宽度按内容自适应，不固定 */
  margin-right: 16px;
}

.rd-value {
  color: var(--ziwi-text-primary, #323233);
  word-break: break-all;
  flex: 1;
  min-width: 0;
  text-align: left;
}

/* 空值态 */
.rd-empty {
  color: var(--ziwi-text-muted, #c8c9cc);
}
</style>
