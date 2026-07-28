<template>
  <div class="space-y-6">
    <!-- 顶部：更新时间 + 手动刷新 -->
    <div class="flex items-center justify-between">
      <p class="text-xs text-gray-400">
        数据更新：{{ stats?.generated_at ? fmtTime(stats.generated_at) : '—' }}
      </p>
      <button
        @click="load"
        :disabled="loading"
        class="text-sm text-blue-600 hover:underline disabled:opacity-50"
      >
        {{ loading ? '刷新中…' : '手动刷新' }}
      </button>
    </div>

    <div v-if="error" class="bg-red-50 text-red-600 text-sm px-4 py-2 rounded-lg">{{ error }}</div>

    <!-- KPI 卡 -->
    <section class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <div class="bg-white rounded-xl border border-gray-200 p-4">
        <p class="text-xs text-gray-400">租户用户</p>
        <p class="text-2xl font-semibold text-gray-800 mt-1">{{ kpi.tenant_users }}</p>
        <p class="text-xs text-green-600 mt-0.5">活跃 {{ kpi.tenant_active }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-4">
        <p class="text-xs text-gray-400">平台账号</p>
        <p class="text-2xl font-semibold text-gray-800 mt-1">{{ kpi.platform_users }}</p>
        <p class="text-xs text-green-600 mt-0.5">启用 {{ kpi.platform_active }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-4">
        <p class="text-xs text-gray-400">业务线</p>
        <p class="text-2xl font-semibold text-gray-800 mt-1">{{ kpi.business_lines }}</p>
        <p class="text-xs text-gray-400 mt-0.5">已开通</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-4">
        <p class="text-xs text-gray-400">有效会话</p>
        <p class="text-2xl font-semibold text-gray-800 mt-1">{{ kpi.active_sessions }}</p>
        <p class="text-xs text-gray-400 mt-0.5">当前在线</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-4">
        <p class="text-xs text-gray-400">待处理工单</p>
        <p class="text-2xl font-semibold text-orange-600 mt-1">{{ kpi.open_tickets }}</p>
        <p class="text-xs text-gray-400 mt-0.5">待支付/审批</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-4">
        <p class="text-xs text-gray-400">有效授权</p>
        <p class="text-2xl font-semibold text-gray-800 mt-1">{{ trade.realtime.active_licenses }}</p>
        <p class="text-xs text-gray-400 mt-0.5">未过期</p>
      </div>
    </section>

    <!-- Token 购销：实时 + 分时 -->
    <section class="bg-white rounded-xl border border-gray-200 p-5">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-base font-semibold text-gray-800">Token 购销（实时 + 分时）</h2>
        <div class="flex gap-2 text-xs">
          <button
            @click="tradeRange = 'day'"
            :class="tradeRange === 'day' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'"
            class="px-3 py-1 rounded-lg"
          >按日 · 30天</button>
          <button
            @click="tradeRange = 'hour'"
            :class="tradeRange === 'hour' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'"
            class="px-3 py-1 rounded-lg"
          >按小时 · 今日</button>
        </div>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div class="bg-blue-50 rounded-lg p-3">
          <p class="text-xs text-blue-500">今日购</p>
          <p class="text-xl font-semibold text-blue-700">{{ trade.realtime.buy_today }}</p>
        </div>
        <div class="bg-green-50 rounded-lg p-3">
          <p class="text-xs text-green-600">今日销</p>
          <p class="text-xl font-semibold text-green-700">{{ trade.realtime.sell_today }}</p>
        </div>
        <div class="bg-orange-50 rounded-lg p-3">
          <p class="text-xs text-orange-600">待处理</p>
          <p class="text-xl font-semibold text-orange-700">{{ trade.realtime.pending }}</p>
        </div>
        <div class="bg-gray-50 rounded-lg p-3">
          <p class="text-xs text-gray-500">购-销净额(今日)</p>
          <p class="text-xl font-semibold text-gray-700">{{ trade.realtime.buy_today - trade.realtime.sell_today }}</p>
        </div>
      </div>

      <div class="h-40 bg-gray-50 rounded-lg p-2">
        <SparkLine
          v-if="tradeSeries.length"
          :series="tradeSeries"
          :W="300" :H="100"
        />
        <p v-else class="text-center text-gray-400 text-sm py-16">暂无数据</p>
      </div>
      <div class="flex gap-4 mt-2 text-xs text-gray-500">
        <span class="flex items-center gap-1"><i class="w-3 h-0.5 bg-blue-500 inline-block"></i>购</span>
        <span class="flex items-center gap-1"><i class="w-3 h-0.5 bg-green-500 inline-block"></i>销</span>
      </div>
    </section>

    <!-- 全量工单统计 -->
    <section class="bg-white rounded-xl border border-gray-200 p-5">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-base font-semibold text-gray-800">全量工单统计</h2>
        <span class="text-sm text-gray-400">共 {{ tickets.total }} 单</span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <!-- 状态分布 -->
        <div>
          <p class="text-sm text-gray-500 mb-2">状态分布</p>
          <div class="space-y-2">
            <div v-for="s in ticketStatusRows" :key="s.key" class="flex items-center gap-2 text-sm">
              <span class="w-20 text-gray-600 shrink-0">{{ s.label }}</span>
              <div class="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
                <div class="h-full bg-blue-500" :style="{ width: s.pct + '%' }"></div>
              </div>
              <span class="w-8 text-right text-gray-700">{{ s.count }}</span>
            </div>
          </div>
          <div class="flex gap-4 mt-3 text-xs text-gray-500">
            <span>新建 {{ tickets.by_type.new || 0 }}</span>
            <span>续费 {{ tickets.by_type.renewal || 0 }}</span>
          </div>
        </div>
        <!-- 趋势 -->
        <div>
          <p class="text-sm text-gray-500 mb-2">工单趋势（近 30 天）</p>
          <div class="h-40 bg-gray-50 rounded-lg p-2">
            <SparkLine v-if="ticketTrend.length" :series="[{ color: '#3b82f6', values: ticketTrend }]" :W="300" :H="100" />
            <p v-else class="text-center text-gray-400 text-sm py-16">暂无数据</p>
          </div>
        </div>
      </div>
    </section>

    <!-- 临期提醒 -->
    <section class="bg-white rounded-xl border border-gray-200 p-5">
      <h2 class="text-base font-semibold text-gray-800 mb-4">临期提醒（未来 90 天）</h2>
      <div v-if="!expiring.length" class="text-sm text-gray-400 py-4">暂无临期授权</div>
      <ul v-else class="divide-y divide-gray-100">
        <li v-for="e in expiring" :key="e.id" class="flex items-center justify-between py-2 text-sm">
          <span class="text-gray-700">{{ e.tenant_name }} · <span class="text-gray-400">{{ e.product }}</span></span>
          <span :class="e.days_left <= 30 ? 'text-red-600' : e.days_left <= 60 ? 'text-orange-600' : 'text-gray-500'">
            {{ e.days_left }} 天后到期
          </span>
        </li>
      </ul>
    </section>

    <!-- 安全（P2 占位） -->
    <section class="bg-white rounded-xl border border-gray-200 p-5">
      <h2 class="text-base font-semibold text-gray-800 mb-3">安全与登录</h2>
      <p class="text-sm text-gray-400">
        登录成功率与失败审计需新增审计表（P2），本期看板以 refresh token 近似登录趋势，精确统计后续补充。
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { cloudApi, extractError } from "../api/cloud-auth";
import SparkLine from "../components/SparkLine.vue";

const stats = ref<any>(null);
const loading = ref(false);
const error = ref("");
const tradeRange = ref<"day" | "hour">("day");

const kpi = computed(() => stats.value?.kpi || {
  tenant_users: 0, tenant_active: 0, platform_users: 0, platform_active: 0,
  business_lines: 0, active_sessions: 0, open_tickets: 0,
});
const trade = computed(() => stats.value?.token_trade || {
  realtime: { buy_today: 0, sell_today: 0, pending: 0, active_licenses: 0 },
  by_hour: [], by_day: [],
});
const tickets = computed(() => stats.value?.tickets || {
  total: 0, by_status: {}, by_type: {}, by_product: [], trend: { '7d': [], '30d': [] },
});
const expiring = computed(() => stats.value?.expiring || []);

const STATUS_LABELS: Record<string, string> = {
  pending: "待支付", paid: "待审批", approved: "已通过", rejected: "已驳回", completed: "已完成",
};

const ticketStatusRows = computed(() => {
  const by = tickets.value.by_status || {};
  const total = Object.values(by).reduce((a: number, b: any) => a + (b || 0), 0) || 1;
  return Object.entries(by).map(([key, count]) => ({
    key,
    label: STATUS_LABELS[key] || key,
    count,
    pct: Math.round(((count as number) / total) * 100),
  }));
});

const ticketTrend = computed(() => (tickets.value.trend?.['30d'] || []).map((d: any) => d.count));

const tradeSeries = computed(() => {
  if (tradeRange.value === "day") {
    const d = trade.value.by_day || [];
    return [
      { color: "#3b82f6", values: d.map((x: any) => x.buy) },
      { color: "#22c55e", values: d.map((x: any) => x.sell) },
    ];
  }
  const h = trade.value.by_hour || [];
  return [
    { color: "#3b82f6", values: h.map((x: any) => x.buy) },
    { color: "#22c55e", values: h.map((x: any) => x.sell) },
  ];
});

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const res = await cloudApi.stats();
    stats.value = res.data?.data ?? res.data;
  } catch (e: any) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>
