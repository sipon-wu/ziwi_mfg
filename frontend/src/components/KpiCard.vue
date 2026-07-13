<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  value: string | number | null
  unit?: string
  trend?: 'up' | 'down' | null
  trendLabel?: string
  color?: string
  /** 三态：real 真实值(含真实0) / loading 加载中 / unavailable 未接入 */
  state?: 'real' | 'loading' | 'unavailable'
}>()

const isLoading = computed(() => props.state === 'loading')
const isUnavailable = computed(() => props.state === 'unavailable')
</script>

<template>
  <div class="kpi-card" :class="{ 'kpi-card--unavailable': isUnavailable }" :style="{ '--accent-color': color || 'var(--ziwi-primary)' }">
    <div class="kpi-accent-bar"></div>
    <div class="kpi-body">
      <div class="kpi-title">{{ title }}</div>
      <div class="kpi-value-row">
        <van-loading v-if="isLoading" size="20" class="kpi-loading" />
        <template v-else-if="isUnavailable">
          <span class="kpi-value kpi-value--unavailable">未接入</span>
        </template>
        <template v-else>
          <span class="kpi-value">{{ value }}</span>
          <span v-if="unit" class="kpi-unit">{{ unit }}</span>
        </template>
      </div>
      <div v-if="trendLabel && !isLoading && !isUnavailable" class="kpi-trend" :class="trend === 'up' ? 'trend-up' : trend === 'down' ? 'trend-down' : ''">
        <van-icon v-if="trend === 'up'" name="arrow-up" />
        <van-icon v-if="trend === 'down'" name="arrow-down" />
        {{ trendLabel }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.kpi-card {
  display: flex;
  background: var(--ziwi-bg-white);
  border-radius: var(--ziwi-radius-lg);
  overflow: hidden;
  box-shadow: var(--ziwi-shadow-card);
}

.kpi-accent-bar {
  width: 4px;
  flex-shrink: 0;
  background: var(--accent-color);
}

.kpi-body {
  flex: 1;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kpi-title {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
  line-height: 1.4;
}

.kpi-value-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.kpi-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--ziwi-text-primary);
  line-height: 1.2;
}

.kpi-unit {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-muted);
  line-height: 1.4;
}

.kpi-loading {
  padding: 4px 0;
}

.kpi-card--unavailable .kpi-accent-bar {
  background: var(--ziwi-text-muted);
}

.kpi-value--unavailable {
  color: var(--ziwi-text-muted);
  font-size: 20px;
}

.kpi-trend {
  font-size: var(--ziwi-font-size-sm);
  line-height: 1.4;
  color: var(--ziwi-text-secondary);
  display: flex;
  align-items: center;
  gap: 2px;
}

.trend-up {
  color: var(--ziwi-success);
}

.trend-down {
  color: var(--ziwi-danger);
}
</style>
