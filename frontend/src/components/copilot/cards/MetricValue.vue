<template>
  <div class="metric-value" :class="{ unavailable: !available }">
    <div class="mv-name">{{ name }}</div>
    <div class="mv-row">
      <span class="mv-value">{{ displayValue }}</span>
      <span v-if="unit && available" class="mv-unit">{{ unit }}</span>
    </div>
    <div v-if="note" class="mv-note">{{ note }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  name: string
  value?: number | null
  formatted?: string
  unit?: string
  note?: string | null
  available?: boolean
}>()

const displayValue = computed(() => {
  if (props.available === false) return '暂不可用'
  return props.formatted || (props.value === null || props.value === undefined ? '—' : String(props.value))
})
</script>

<style scoped>
.metric-value {
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-lg);
  padding: 12px 14px;
  box-shadow: var(--ziwi-shadow-card);
}
.metric-value.unavailable {
  background: var(--ziwi-bg-light);
}
.mv-name {
  font-size: var(--ziwi-font-size-sm, 12px);
  color: var(--ziwi-text-secondary);
  margin-bottom: 6px;
}
.mv-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.mv-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--ziwi-primary);
  line-height: 1.2;
}
.unavailable .mv-value {
  color: var(--ziwi-text-muted);
  font-size: 18px;
}
.mv-unit {
  font-size: var(--ziwi-font-size-sm, 12px);
  color: var(--ziwi-text-muted);
}
.mv-note {
  margin-top: 6px;
  font-size: 11px;
  color: var(--ziwi-warning);
}
</style>
