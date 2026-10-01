<template>
  <div v-if="source" class="source-footnote">
    <span class="sf-icon">ℹ</span>
    <span class="sf-text">
      来源：{{ source.modules }} · {{ source.table_or_caliber }}
      <template v-if="source.caliber"> ｜口径：{{ source.caliber }}</template>
      <template v-if="source.time_range"> ｜范围：{{ source.time_range }}</template>
      ｜记录 {{ source.record_count }} 条
      <template v-if="source.note"> ｜{{ source.note }}</template>
    </span>
  </div>
</template>

<script setup lang="ts">
import type { SourceFootnote } from '@/types/copilot'

defineProps<{ source: SourceFootnote | null }>()
</script>

<style scoped>
.source-footnote {
  display: flex;
  gap: 4px;
  margin-top: 8px;
  padding: 6px 8px;
  background: var(--ziwi-bg-light);
  border-radius: var(--ziwi-radius-sm);
  font-size: 11px;
  color: var(--ziwi-text-muted);
  line-height: 1.5;
}
.sf-icon {
  flex-shrink: 0;
  color: var(--ziwi-info);
}
.sf-text {
  word-break: break-all;
}
</style>
