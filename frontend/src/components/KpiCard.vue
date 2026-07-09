<script setup lang="ts">
defineProps<{
  title: string
  value: string | number
  unit?: string
  trend?: 'up' | 'down' | null
  trendLabel?: string
  color?: string
}>()
</script>

<template>
  <div class="kpi-card" :style="{ '--accent-color': color || 'var(--ziwi-primary)' }">
    <div class="kpi-accent-bar"></div>
    <div class="kpi-body">
      <div class="kpi-title">{{ title }}</div>
      <div class="kpi-value-row">
        <span class="kpi-value">{{ value }}</span>
        <span v-if="unit" class="kpi-unit">{{ unit }}</span>
      </div>
      <div v-if="trendLabel" class="kpi-trend" :class="trend === 'up' ? 'trend-up' : trend === 'down' ? 'trend-down' : ''">
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
