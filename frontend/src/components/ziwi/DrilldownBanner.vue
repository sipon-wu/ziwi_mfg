<script setup lang="ts">
/**
 * 驾驶舱下探条件提示条。
 *
 * 为什么必须有一条可见的提示：下探条件藏在 URL query 里，用户从 KPI 卡跳进来
 * 看到的是一个"少了几行"的列表。没有任何标记时他会以为这就是全部数据，
 * 或者想看全量却找不到开关 —— 一个看不见的过滤就是陷阱。
 *
 * 三个信息缺一不可：
 *   1. **来源**（label）：说明这是驾驶舱下探视图，不是列表本身变小了
 *   2. **总量**：与 KPI 卡上的数字对得上，才算真的下探成功
 *   3. **截断**：单状态 > 100 条时明说，不许假装列全了
 * 加上「清除下探」按钮，由 `useDrilldown.clear()` + 各页注册的 `onChange`
 * 回到常规分页视图。
 */
import { computed } from 'vue'
import { useDrilldown } from '@/composables/useDrilldown'

const props = defineProps<{ total?: number | null }>()
const { active, label, truncated, clear } = useDrilldown()
const countText = computed(() => (props.total == null ? '' : `共 ${props.total} 条`))
</script>

<template>
  <div v-if="active" class="drill-banner" role="status">
    <van-icon name="filter-o" class="drill-banner__icon" />
    <span class="drill-banner__label">{{ label }}</span>
    <span v-if="countText" class="drill-banner__count">{{ countText }}</span>
    <span v-if="truncated" class="drill-banner__warn">
      单状态超过 100 条，仅显示前 100 条
    </span>
    <van-button class="drill-banner__clear" size="mini" plain type="primary" @click="clear">
      清除下探
    </van-button>
  </div>
</template>

<style scoped>
.drill-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-height: var(--ziwi-touch-min, 48px);
  margin: 8px;
  padding: 6px 12px;
  border: 1px solid var(--ziwi-primary);
  border-radius: var(--ziwi-radius-md);
  background: var(--ziwi-primary-bg);
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-primary);
}
.drill-banner__icon { color: var(--ziwi-primary); }
.drill-banner__label { font-weight: 600; }
.drill-banner__count { color: var(--ziwi-text-secondary); font-variant-numeric: tabular-nums; }
.drill-banner__warn {
  width: 100%;
  color: var(--ziwi-warning);
  font-size: var(--ziwi-font-size-xs);
}
.drill-banner__clear { margin-left: auto; flex: 0 0 auto; }
</style>
