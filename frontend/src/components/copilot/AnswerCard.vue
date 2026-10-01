<template>
  <div class="answer-card">
    <div v-if="payload.narrative" class="ac-narrative">{{ payload.narrative }}</div>

    <!-- 复合问句：多指标卡片网格 -->
    <div v-if="cards.length" class="ac-cards">
      <MetricValue
        v-for="c in cards"
        :key="c.metric_code"
        :name="c.name || c.metric_code"
        :value="c.value"
        :formatted="c.formatted"
        :unit="c.unit"
        :note="c.note"
        :available="c.available"
      />
    </div>

    <template v-else>
      <div v-if="showMetric" class="ac-block">
        <MetricValue
          :name="name"
          :value="data.value"
          :formatted="data.formatted"
          :unit="data.unit"
          :note="data.note"
          :available="data.available !== false"
        />
      </div>
      <div v-if="showTable" class="ac-block">
        <DataTable :columns="columns" :rows="rows" />
      </div>
      <div v-if="showChart" class="ac-block">
        <MiniChart :rows="seriesRows" :type="chartType" />
      </div>
    </template>

    <SourceFootnote v-if="payload.source" :source="payload.source" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AnswerPayload } from '@/types/copilot'
import DataTable from './cards/DataTable.vue'
import MetricValue from './cards/MetricValue.vue'
import MiniChart from './cards/MiniChart.vue'
import SourceFootnote from './SourceFootnote.vue'

const props = defineProps<{ payload: AnswerPayload }>()

const data = computed(() => props.payload.data || {})
const cards = computed(() => data.value.cards || [])
const rows = computed(() => data.value.rows || [])
const columns = computed(() => data.value.columns || [])
const seriesRows = computed(() =>
  (data.value.series || [])
    .filter((s) => s.name !== null && s.name !== undefined)
    .map((s) => ({ label: String(s.name), value: s.value as number | null })),
)
const name = computed(() => data.value.name || props.payload.metric_code)
const viz = computed(() => props.payload.viz_hint || 'metric')
const wants = (token: string) => viz.value.split('+').includes(token)

const showMetric = computed(() => {
  if (wants('metric')) return true
  // 单值结果兜底：无表格/图表时也展示数值卡
  return rows.value.length <= 1 && seriesRows.value.length <= 1
})
const showTable = computed(() => viz.value === 'table' && rows.value.length > 0)
const showChart = computed(() => wants('line') || wants('bar'))
const chartType = computed<'bar' | 'line'>(() => (wants('line') ? 'line' : 'bar'))
</script>

<style scoped>
.answer-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ac-narrative {
  font-size: 13px;
  color: var(--ziwi-text-regular);
  line-height: 1.6;
  white-space: pre-wrap;
}
.ac-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}
.ac-block {
  width: 100%;
}
</style>
