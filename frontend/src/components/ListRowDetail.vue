<script setup lang="ts">
import { computed } from 'vue'
import type { FieldDef, FieldGroup } from '@/types/search'

const props = defineProps<{
  item: Record<string, any>
  fields: FieldDef[]
}>()

const GROUP_ORDER: { key: FieldGroup; title: string }[] = [
  { key: 'basic', title: '基础信息' },
  { key: 'relation', title: '关联信息' },
  { key: 'audit', title: '审计信息' },
]

const grouped = computed(() => {
  return GROUP_ORDER.map((g) => ({
    ...g,
    fields: props.fields.filter((f) => (f.group || 'basic') === g.key),
  })).filter((g) => g.fields.length > 0)
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
    <div v-for="g in grouped" :key="g.key" class="rd-group">
      <div class="rd-group-title">{{ g.title }}</div>
      <div class="rd-grid">
        <div v-for="f in g.fields" :key="f.key" class="rd-item" :class="{ 'rd-item--full': f.type === 'string' && f.key === 'remark' }">
          <span class="rd-label">{{ f.label }}</span>
          <span class="rd-value" :class="{ 'rd-empty': display(f) === '--' }">{{ display(f) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row-detail {
  padding: 10px 12px 12px;
  background: var(--ziwi-bg-light, #f7f8fa);
  border-top: 1px dashed var(--ziwi-border, #ebedf0);
}
.rd-group + .rd-group {
  margin-top: 10px;
}
.rd-group-title {
  font-size: 12px;
  color: var(--ziwi-text-muted, #969799);
  margin-bottom: 6px;
  font-weight: 600;
}
.rd-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 12px;
}
.rd-item {
  display: flex;
  flex-direction: column;
  font-size: 13px;
  line-height: 1.4;
}
.rd-item--full {
  grid-column: 1 / -1;
}
.rd-label {
  color: var(--ziwi-text-muted, #969799);
}
.rd-value {
  color: var(--ziwi-text-primary, #323233);
  word-break: break-all;
}
.rd-empty {
  color: var(--ziwi-text-muted, #c8c9cc);
}
</style>
