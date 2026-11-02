<script setup lang="ts">
/**
 * 生产看板
 *
 * ## 本轮修正的三处「不诚实」
 * 改造前这一页是脚手架期的占位实现，三处数据都在误导用户：
 * 1. **标签撒谎**：卡名写「今日工单 / 今日报工」，但取的是 `/work-orders` 与
 *    `/work-reports` 的 `total`（**全量**条数），不是今日。已改为「工单总数 / 报工总数」。
 * 2. **死值冒充真实值**：第三张「产出总量」的 `stats.output` **从未被赋值**，永远是 0，
 *    却以真实值的样子渲染。现在按 `KpiCard` 的三态语义显式标 `unavailable`（显示「未接入」）。
 * 3. **假趋势**：「较昨日持平」是硬编码字符串，三张卡都写死，与数据无关。没有真实环比
 *    数据就不显示趋势 —— 宁可不显示，也不给一个编造的结论。
 *
 * ## 为什么改用 KpiCard 组件
 * 改造前这里是手写的 `.kpi-card` 结构，落到 `ziwi-variables.css` 的全局类（3px 竖条）；
 * 而 `components/KpiCard.vue`（驾驶舱/车间大屏/安灯/能碳设备在用）用的是 4px accent bar +
 * 三态 + trend 图标 + 全令牌化。同一个产品里两套 KPI 卡并存，竖条粗细都不一样。
 *
 * ## 已知未解决
 * 首屏只有一行三张卡，下方约 80% 是空白。这是**内容缺失**，不是样式问题 ——
 * 需要先定义「这个看板给谁看、要回答什么问题」，再接图表/待办/趋势，属于产品决策，
 * 不在样式修正范围内。
 */
import { onMounted, ref } from 'vue'
import { get } from '@/api/client'
import { showToast } from 'vant'
import KpiCard from '@/components/KpiCard.vue'
import type { PaginatedResponse, WorkOrder, WorkReport } from '@/types'

type KpiState = 'real' | 'loading' | 'unavailable'

const stats = ref({ orders: 0, reports: 0 })
const state = ref<KpiState>('loading')

onMounted(async () => {
  try {
    // 两个请求互不依赖，并行取，避免串行等待
    const [orders, reports] = await Promise.all([
      get<PaginatedResponse<WorkOrder>>('/work-orders', { page: 1, page_size: 1 }),
      get<PaginatedResponse<WorkReport>>('/work-reports', { page: 1, page_size: 1 }),
    ])
    stats.value.orders = orders.total || 0
    stats.value.reports = reports.total || 0
    state.value = 'real'
  } catch {
    // 接口不可达时按「未接入」处理，而不是把 0 当真实值显示
    state.value = 'unavailable'
    showToast('看板数据获取失败')
  }
})
</script>

<template>
  <div class="dashboard-page">
    <h2 class="dashboard-title">生产看板</h2>
    <div class="kpi-row">
      <KpiCard title="工单总数" :value="stats.orders" unit="个" :state="state" />
      <KpiCard title="报工总数" :value="stats.reports" unit="条" :state="state" />
      <!-- 产出数据源尚未接入：显式标注，不给假 0 -->
      <KpiCard title="产出总量" :value="null" unit="件" state="unavailable" />
    </div>
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: 0;
}

.dashboard-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--ziwi-text-primary);
  margin-bottom: 20px;
}

/* auto-fit + minmax 而非 flex:1 —— 412px 的手机宽里塞三张 flex:1 卡片，
   每张只剩约 110px，「未接入」会被压成竖排三行。auto-fit 在放不下时
   自动塌成单列，放得下时把空轨道收掉让三张卡等分，不需要写断点。
   （与 pages/system/RolePermissions.vue 的写法保持一致）

   最小列宽取 200px 而不是 220px：T 档（900 宽、侧栏 176）内容区约 676px，
   220 时 3×220+2×16=692 差 16px 放不下，会退化成「两张一行 + 一张孤零零」，
   右下角留一块空格；200 时 3×200+2×16=632 刚好放得下。H 档 380px 下
   2×200+16=416 仍然放不下，照旧塌成单列。 */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}
</style>
