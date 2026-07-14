<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast } from 'vant'
import { get } from '@/api/client'

const route = useRoute()
const router = useRouter()
const orderId = Number(route.params.id)

const order = ref<any>(null)
const loading = ref(false)
const items = ref<any[]>([])

const statusMap: Record<string, string> = {
  pending: '待收货', inspecting: '待检', partially_stored: '部分上架',
  stored: '已完成', cancelled: '已取消',
}
const statusColor: Record<string, string> = {
  pending: 'warning', inspecting: 'primary', partially_stored: 'warning',
  stored: 'success', cancelled: 'danger',
}
const typeMap: Record<string, string> = {
  purchase: '采购入库', '生产入库': '生产入库', '退货入库': '退货入库', transfer: '调拨入库',
}

async function fetchOrder() {
  loading.value = true
  try {
    const res: any = await get(`/wms/receipt-orders/${orderId}`)
    order.value = res
    // 尝试加载明细（如果接口返回 items 字段）
    if (res.items) {
      items.value = res.items
    }
  } catch {
    showToast('加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchOrder)

function goBack() { router.push('/wms/receipt-orders') }
</script>

<template>
  <div>
    <van-nav-bar :title="order?.receipt_no || '入库单详情'" left-arrow @click-left="goBack" />

    <div v-if="loading" style="padding: 40px; text-align: center">
      <van-loading />
    </div>

    <div v-else-if="order">
      <!-- 基本信息 -->
      <van-cell-group title="基本信息">
        <van-cell title="入库单号" :value="order.receipt_no" />
        <van-cell title="入库类型" :value="typeMap[order.receipt_type] || order.receipt_type" />
        <van-cell title="状态">
          <van-tag :type="(statusColor[order.status] as any) || 'default'" size="medium">
            {{ statusMap[order.status] || order.status }}
          </van-tag>
        </van-cell>
        <van-cell v-if="order.source_type" title="来源类型" :value="order.source_type" />
        <van-cell v-if="order.source_doc_no" title="来源单号" :value="order.source_doc_no" />
        <van-cell title="仓库" :value="order.warehouse_name || `ID: ${order.warehouse_id}`" />
        <van-cell v-if="order.supplier_id" title="供应商ID" :value="order.supplier_id" />
      </van-cell-group>

      <!-- 数量信息 -->
      <van-cell-group title="数量信息">
        <van-cell title="应收总数" :value="order.total_qty?.toString() || '0'" />
        <van-cell title="实收数量" :value="order.received_qty?.toString() || '0'" />
        <van-cell title="已上架数量" :value="order.stored_qty?.toString() || '0'" />
      </van-cell-group>

      <!-- 时间信息 -->
      <van-cell-group title="时间信息">
        <van-cell v-if="order.created_at" title="创建时间" :value="order.created_at?.slice(0, 19).replace('T', ' ')" />
        <van-cell v-if="order.completed_at" title="完成时间" :value="order.completed_at?.slice(0, 19).replace('T', ' ')" />
      </van-cell-group>

      <!-- 明细列表 -->
      <van-cell-group v-if="items.length > 0" title="明细">
        <van-cell v-for="(item, idx) in items" :key="item.id || idx">
          <template #title>
            <span>行号 {{ item.line_no }}</span>
          </template>
          <template #label>
            <div>物料ID: {{ item.material_id }}</div>
            <div>应收: {{ item.expected_qty }} | 实收: {{ item.received_qty }} | 上架: {{ item.stored_qty }}</div>
            <div v-if="item.unit">单位: {{ item.unit }}</div>
            <div v-if="item.batch_no">批次: {{ item.batch_no }}</div>
            <div v-if="item.remark">备注: {{ item.remark }}</div>
          </template>
        </van-cell>
      </van-cell-group>
    </div>

    <div v-else style="padding: 40px; text-align: center; color: #999">
      入库单不存在
    </div>
  </div>
</template>
