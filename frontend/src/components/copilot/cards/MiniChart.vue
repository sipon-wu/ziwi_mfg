<template>
  <div ref="chartEl" class="mini-chart"></div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  rows: { label: string | null; value: number | null }[]
  /** bar | line */
  type?: 'bar' | 'line'
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const labels = props.rows.map((r) => (r.label === null ? '—' : String(r.label)))
  const values = props.rows.map((r) => (r.value === null || r.value === undefined ? 0 : Number(r.value)))
  chart.setOption(
    {
      grid: { left: 6, right: 10, top: 18, bottom: 4, containLabel: true },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { fontSize: 10, interval: 0, rotate: labels.length > 4 ? 30 : 0 },
      },
      yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
      series: [
        {
          type: props.type || 'bar',
          data: values,
          smooth: true,
          barMaxWidth: 28,
          itemStyle: { color: '#0d7377' },
          areaStyle: props.type === 'line' ? { opacity: 0.12 } : undefined,
        },
      ],
    },
    true,
  )
}

onMounted(() => nextTick(render))
watch(
  () => props.rows,
  () => nextTick(render),
  { deep: true },
)
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.mini-chart {
  width: 100%;
  height: 180px;
}
</style>
