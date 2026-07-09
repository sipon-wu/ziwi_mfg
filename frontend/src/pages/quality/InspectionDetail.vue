<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '@/api/client'

const route = useRoute()
const order = ref<any>(null)

async function fetch() {
  const res = await get(`/inspection-orders/${route.params.id}`)
  order.value = res
}

onMounted(fetch)
</script>

<template>
  <div v-if="order" style="padding:16px;">
    <van-cell-group title="检验单信息">
      <van-cell title="检验单号" :value="'#'+order.id" />
      <van-cell title="检验类型" :value="order.qc_type || '-'" />
      <van-cell title="状态" :value="order.status || '-'" />
      <van-cell title="检验结果" :value="order.judge_result || '-'" />
      <van-cell title="创建时间" :value="order.created_at || '-'" />
    </van-cell-group>
  </div>
  <van-empty v-else description="加载中..." />
</template>
