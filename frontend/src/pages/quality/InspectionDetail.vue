<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, put } from '@/api/client'
import { showToast } from 'vant'

const route = useRoute()
const router = useRouter()

// 对齐后端：order_type ∈ first/inspection/spot_check；result ∈ ACC/REJ/UAI（未判定 pending）
const ORDER_TYPE_MAP: Record<string, string> = {
  first: '首件检验',
  inspection: '过程检验',
  spot_check: '抽检',
}
const RESULT_MAP: Record<string, string> = {
  pending: '待判定',
  ACC: '合格',
  REJ: '不合格',
  UAI: '待判定',
}

const order = ref<any>(null)
const judging = ref(false)

async function fetch() {
  order.value = await get(`/inspection-orders/${route.params.id}`)
}

async function judge(result: string) {
  judging.value = true
  try {
    const res: any = await put(`/inspection-orders/${route.params.id}/judge`, { result })
    if (result === 'REJ' && res?.ncr_id) {
      showToast(`已自动发起不合格评审 #${res.ncr_id}`)
    } else if (result === 'ACC') {
      showToast('判定为合格')
    } else if (result === 'UAI') {
      showToast('已标记待判定')
    } else {
      showToast('判定完成')
    }
    await fetch()
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '判定失败')
  } finally {
    judging.value = false
  }
}

onMounted(fetch)
</script>

<template>
  <div v-if="order">
    <van-nav-bar title="检验详情" left-arrow @click-left="() => router.push('/quality')" />
    <div style="padding:16px;">
      <van-cell-group title="检验单信息">
        <van-cell title="检验单号" :value="order.order_no || ('#' + order.id)" />
        <van-cell title="检验类型" :value="ORDER_TYPE_MAP[order.order_type] || order.order_type || '-'" />
        <van-cell title="判定结果" :value="RESULT_MAP[order.result] || order.result || '-'" />
        <van-cell title="创建时间" :value="order.created_at || '-'" />
        <van-cell v-if="order.remark" title="备注" :value="order.remark" />
      </van-cell-group>

      <van-cell-group title="判定" style="margin-top:12px;">
        <div style="padding:12px; display:flex; gap:10px;">
          <van-button type="success" size="small" :loading="judging" @click="judge('ACC')">合格</van-button>
          <van-button type="danger" size="small" :loading="judging" @click="judge('REJ')">不合格</van-button>
          <van-button type="warning" size="small" :loading="judging" @click="judge('UAI')">待判定</van-button>
        </div>
        <van-cell
          v-if="order.result === 'REJ'"
          title="已自动发起不合格评审（NCR）"
          is-link
          @click="router.push('/quality/ncr')"
          value="查看"
        />
      </van-cell-group>
    </div>
  </div>
  <van-empty v-else description="加载中..." />
</template>
