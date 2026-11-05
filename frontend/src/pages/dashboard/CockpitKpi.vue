<script setup lang="ts">
import { computed } from 'vue'
import type { KpiState } from '@/types/search'

/**
 * 驾驶舱专用 KPI 卡。
 *
 * 与通用 `KpiCard` 的差别（刻意不复用，避免影响其他看板）：
 * - 支持**占比进度条**：有分母的指标（在制/工单、未处理/呼叫、逾期/待保养）
 *   显示一条细进度条，否则一串孤立数字读者无法判断"这个 6 是大还是小"
 * - 支持**异常语义着色**：逾期保养、未结 NCR、库存预警这类"归零才是正常"的
 *   指标，> 0 才染橙/红；全部正常时页面应该安静
 * - 卡头左侧色条与数值同色，扫一眼就能定位异常项
 */
const props = defineProps<{
  label: string
  value: number | string | null
  unit?: string
  state: KpiState
  /** 0..1。给得出分母的指标；无分母不传，就不画进度条 */
  ratio?: number | null
  /** 进度条右侧文字，如 "60%"；不传则用 percentage */
  ratioText?: string
  /** 异常语义：normal 品牌色 / warn 橙 / danger 红 */
  severity?: 'normal' | 'warn' | 'danger'
  /** 口径说明，悬停可见 —— 避免每张卡都堆一行小字把版面撑乱 */
  hint?: string
}>()

const isLoading = computed(() => props.state === 'loading')
const unavailable = computed(() => props.state === 'unavailable')

/**
 * ★ 未接入/加载中一律走 normal 色：否则一个接口挂了，整列都染成红色，
 *   真正的异常（逾期保养 3 台）反而被淹掉。
 */
const tone = computed(() =>
  props.state === 'real' ? (props.severity || 'normal') : 'normal',
)

const pct = computed(() => {
  const r = props.ratio
  if (r == null || Number.isNaN(r)) return null
  return Math.max(0, Math.min(100, Math.round(r * 100)))
})
</script>

<template>
  <div
    class="ck"
    :class="[`ck--${tone}`, { 'ck--muted': unavailable }]"
    :title="hint || ''"
  >
    <div class="ck__body">
      <div class="ck__label">{{ label }}</div>

      <div v-if="isLoading" class="ck__loading">
        <van-loading size="16" />
      </div>
      <div v-else-if="unavailable" class="ck__value ck__value--muted">未接入</div>
      <div v-else class="ck__value-row">
        <span class="ck__value">{{ value }}</span>
        <span v-if="unit" class="ck__unit">{{ unit }}</span>
      </div>

      <div v-if="pct !== null && !isLoading && !unavailable" class="ck__ratio">
        <div class="ck__track">
          <div class="ck__fill" :style="{ width: `${pct}%` }" />
        </div>
        <span class="ck__ratio-text">{{ ratioText || `${pct}%` }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
   块状 KPI
   ------------------------------------------------------------
   原来的写法是「白卡 + 左侧 3px 竖条 + 细进度线」：一个数字身上挂了
   三条细线，24 组散在页面上就是一堆点和线，聚不成块面。
   现在反过来 —— **一个 KPI 就是一块实心色块**：
     · 去掉左边竖条和描边，改用整块浅色底承担"这是一个独立单元"
     · 数值放大、颜色加深，块内只有"标签 / 数字 / 占比条"三层
     · 只有异常（逾期、未结、预警）才换块底色 —— 正常态一律冷色，页面安静
   `color-mix` 用来从品牌色派生浅底，先写死一个 fallback 再覆盖：
   老内核不认 color-mix 时退化成纯色，不会变成透明。
   ============================================================ */
.ck {
  --ck-tone: var(--ziwi-primary);
  --ck-soft: #eef5f4;
  --ck-soft: color-mix(in srgb, var(--ziwi-primary) 9%, #ffffff);
  --ck-track: #d8e6e4;
  --ck-track: color-mix(in srgb, var(--ziwi-primary) 20%, #ffffff);

  display: flex;
  min-width: 0;
  background: var(--ck-soft);
  border-radius: var(--ziwi-radius-lg);
}

.ck--warn {
  --ck-tone: var(--ziwi-warning);
  --ck-soft: #fdf3e2;
  --ck-soft: color-mix(in srgb, var(--ziwi-warning) 14%, #ffffff);
  --ck-track: #f4e0bc;
  --ck-track: color-mix(in srgb, var(--ziwi-warning) 26%, #ffffff);
}

.ck--danger {
  --ck-tone: var(--ziwi-danger);
  --ck-soft: #fceeee;
  --ck-soft: color-mix(in srgb, var(--ziwi-danger) 12%, #ffffff);
  --ck-track: #f3d3d3;
  --ck-track: color-mix(in srgb, var(--ziwi-danger) 24%, #ffffff);
}

.ck--muted {
  --ck-soft: var(--ziwi-bg-light);
  --ck-track: var(--ziwi-border-light);
}

.ck__body {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  /* 卡片被同行拉高时内容整体居中 —— 顶对齐会在底部留一条莫名其妙的空白 */
  justify-content: center;
  /* ★ 块内水平居中：块宽固定（同一行等宽），数字只有两三位时左对齐会
     让右半块空着，一块块看过去"左重右轻"，反而更散。居中后每块的重心
     都在中线，整片 KPI 才像一面砖墙而不是一堆散落的数字。 */
  align-items: center;
  text-align: center;
  gap: var(--ziwi-gap-xs);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
}

.ck__label {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-secondary);
  line-height: var(--ziwi-lineheight-tight);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ck__value-row {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: var(--ziwi-gap-sm);
  min-width: 0;
}
.ck__value {
  font-size: 30px;
  font-weight: 700;
  line-height: var(--ziwi-lineheight-tight);
  color: var(--ck-tone);
  font-variant-numeric: tabular-nums;
}
/* 正常态用主文字色，只有异常才让数字本身染色 —— 否则满屏彩色数字 */
.ck--normal .ck__value { color: var(--ziwi-text-primary); }
.ck__value--muted {
  font-size: var(--ziwi-font-size-lg);
  font-weight: 400;
  color: var(--ziwi-text-placeholder);
}

.ck__unit {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

.ck__loading { padding: var(--ziwi-gap-xs) 0; }

.ck__ratio {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  width: 100%;
}
.ck__track {
  flex: 1 1 auto;
  height: 6px;
  border-radius: 3px;
  background: var(--ck-track);
  overflow: hidden;
}
.ck__fill {
  height: 100%;
  background: var(--ck-tone);
  border-radius: 3px;
  transition: width 0.3s ease;
}
.ck--normal .ck__fill { background: var(--ziwi-primary); }
.ck__ratio-text {
  flex: 0 0 auto;
  font-size: var(--ziwi-font-size-xs);
  color: var(--ziwi-text-muted);
  font-variant-numeric: tabular-nums;
}
</style>
