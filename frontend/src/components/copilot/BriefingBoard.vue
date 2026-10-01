<template>
  <div class="briefing-board">
    <div v-if="loading" class="bb-loading">
      <van-loading size="20" /> <span>正在生成简报…</span>
    </div>

    <template v-else-if="briefing">
      <div class="bb-title">{{ briefing.title }}</div>
      <div class="bb-grid">
        <MetricValue
          v-for="card in briefing.cards"
          :key="card.metric_code"
          :name="card.label"
          :value="card.value"
          :formatted="card.formatted"
          :unit="card.unit"
          :note="card.note"
          :available="card.available"
        />
      </div>
      <div v-if="briefing.note" class="bb-note">{{ briefing.note }}</div>
    </template>

    <div v-else class="bb-empty">点击上方角色查看简报</div>
  </div>
</template>

<script setup lang="ts">
import type { BriefingResult } from '@/types/copilot'
import MetricValue from './cards/MetricValue.vue'

defineProps<{ briefing: BriefingResult | null; loading?: boolean }>()
</script>

<style scoped>
.briefing-board {
  padding: 12px;
}
.bb-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ziwi-text-muted);
  font-size: 13px;
  padding: 20px 0;
  justify-content: center;
}
.bb-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ziwi-text-primary);
  margin-bottom: 10px;
}
.bb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}
.bb-note {
  margin-top: 10px;
  font-size: 12px;
  color: var(--ziwi-text-muted);
}
.bb-empty {
  text-align: center;
  color: var(--ziwi-text-muted);
  font-size: 13px;
  padding: 24px 0;
}
</style>
