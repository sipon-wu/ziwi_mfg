<template>
  <div class="data-table">
    <table>
      <thead>
        <tr>
          <th v-for="col in columns" :key="col.key">{{ col.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, ri) in rows" :key="ri">
          <td v-for="col in columns" :key="col.key">{{ cellText(row[col.key]) }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="!rows.length" class="dt-empty">无数据</div>
  </div>
</template>

<script setup lang="ts">
import type { AnswerColumn } from '@/types/copilot'

const props = defineProps<{
  columns: AnswerColumn[]
  rows: Record<string, any>[]
}>()

function cellText(v: any): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return String(Math.round(v * 1000) / 1000)
  return String(v)
}
</script>

<style scoped>
.data-table {
  overflow-x: auto;
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-md);
  background: var(--ziwi-bg-white);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th,
td {
  padding: 6px 10px;
  text-align: left;
  border-bottom: 1px solid var(--ziwi-border-light);
  white-space: nowrap;
}
th {
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-secondary);
  font-weight: 600;
}
tr:last-child td {
  border-bottom: none;
}
.dt-empty {
  padding: 10px;
  text-align: center;
  color: var(--ziwi-text-muted);
  font-size: 12px;
}
</style>
