<script setup lang="ts">
import { computed } from 'vue'
import type { KpiState } from '@/types/search'

/**
 * 通用 KPI 卡（安灯 / 车间大屏 / 能耗 / 首页）。
 *
 * ★ `state` 是**必填**（2026-11-08 收紧，原为可选）：
 *   可选时调用方漏传不会报错，模板就落到 `{{ value }}` 分支 ——
 *   `value` 为 `null` 时渲染成一张**空卡**，既不是 0 也不是「未接入」，
 *   看着像正常但什么都没说。这正是「脏值静默冒充正常值」的形状，
 *   而且 TS 拦不住（漏传可选 prop 合法）。改成必填后 vue-tsc 会把
 *   每个漏传的调用点逐条报出来，等于把契约交给编译器守。
 *
 * 与驾驶舱专用 `CockpitKpi` 的分工（**刻意不复用**，见该文件头注释）：
 *   本组件 = 4px 左侧色条 + 白卡，指标间无分母、无下探；
 *   CockpitKpi = 实心色块 + 占比进度条 + 异常语义着色 + 下探 `to`。
 *   两者**视觉不同是有意的**，共同的只有三态语义，由 `KpiState` 单一真源约束。
 */
const props = defineProps<{
  title: string
  value: string | number | null
  unit?: string
  trend?: 'up' | 'down' | null
  trendLabel?: string
  color?: string
  /** 三态：real 真实值(含真实0) / loading 加载中 / unavailable 未接入 */
  state: KpiState
}>()

const isLoading = computed(() => props.state === 'loading')

/**
 * ★ 「未接入」的判定 = 显式声明 unavailable **或** 读数为空。
 *
 * 为什么要并上读数：`state: 'real'` 配一个 `null` 是自相矛盾的输入
 * （真实态就必须有真值）。这种矛盾不该渲染成空白，也不该兜底成 0，
 * 一律按「未接入」显示 —— 让错误在界面上可见，而不是被空白掩盖。
 * NaN 同理：`Number.NaN` 走到 `{{ }}` 会印出 "NaN" 这种更糟的东西。
 */
const isBlank = computed(() => {
  const v = props.value
  if (v === null || v === undefined) return true
  return typeof v === 'number' && Number.isNaN(v)
})
const isUnavailable = computed(
  () => props.state === 'unavailable' || (!isLoading.value && isBlank.value),
)
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
