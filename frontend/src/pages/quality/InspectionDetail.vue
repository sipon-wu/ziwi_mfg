<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api/client'

const route = useRoute()
const router = useRouter()

// 后端实际字段为 order_type（仅 first/inspection/spot_check，见 models/quality.py:60）与 result（ACC/REJ/UAI，未判定时为 pending）
// 这里同时保留 QA 命名的 qc_type/status/judge_result 作为兜底，绝不留空
const ORDER_TYPE_MAP: Record<string, string> = {
  first: '首件检验',
  inspection: '过程检验',
  spot_check: '抽检',
}
const STATUS_MAP: Record<string, string> = {
  pending: '待检验',
  inspecting: '检验中',
  completed: '已完成',
  closed: '已关闭',
  rejected: '已驳回',
  ACC: '已合格',
  REJ: '已不合格',
  UAI: '待判定',
}
const JUDGE_MAP: Record<string, string> = {
  ACC: '合格',
  REJ: '不合格',
  UAI: '待判定',
  pass: '合格',
  fail: '不合格',
  pending: '待判定',
  conditional: '有条件接收',
}

const order = ref<any>(null)

async function fetch() {
  const res = await get(`/inspection-orders/${route.params.id}`)
  order.value = res
}

onMounted(fetch)
</script>

<template>
  <div v-if="order">
    <van-nav-bar title="检验详情" left-arrow @click-left="() => router.push('/quality')" />
    <div style="padding:16px;">
      <van-cell-group title="检验单信息">
        <van-cell title="检验单号" :value="'#'+order.id" />
        <van-cell title="检验类型" :value="ORDER_TYPE_MAP[order.order_type] || order.qc_type || order.order_type || '-'" />
        <van-cell title="状态" :value="STATUS_MAP[order.status] || STATUS_MAP[order.result] || order.status || order.result || '-'" />
        <van-cell title="检验结果" :value="JUDGE_MAP[order.judge_result] || JUDGE_MAP[order.result] || order.judge_result || order.result || '-'" />
        <van-cell title="创建时间" :value="order.created_at || '-'" />
      </van-cell-group>
    </div>
  </div>
  <van-empty v-else description="加载中..." />
</template>
