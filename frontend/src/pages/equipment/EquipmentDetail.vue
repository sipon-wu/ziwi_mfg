<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { get, put } from '@/api/client'
import type { Equipment } from '@/types'
import { showConfirmDialog, showToast } from 'vant'

const router = useRouter()
const route = useRoute()
const equipment = ref<Equipment | null>(null)
const loading = ref(false)
const actionLoading = ref(false)

const statusLabels: Record<string, string> = {
  running: '运行中',
  idle: '空闲',
  maintenance: '维护中',
  fault: '故障',
  scrapped: '已报废',
}

const statusTypes: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  running: 'success',
  idle: 'primary',
  maintenance: 'warning',
  fault: 'danger',
  scrapped: 'default',
}

async function fetchDetail() {
  const id = Number(route.params.id)
  if (!id) return
  loading.value = true
  try {
    equipment.value = await get<Equipment>(`/equipment/${id}`)
  } finally {
    loading.value = false
  }
}

async function toggleStatus() {
  if (!equipment.value) return
  const isRunning = equipment.value.status === 'running'
  const action = isRunning ? '停用' : '启用'
  try {
    await showConfirmDialog({
      title: '确认操作',
      message: `确定要${action}设备「${equipment.value.equipment_name}」吗？`,
    })
  } catch {
    return
  }
  actionLoading.value = true
  try {
    const updated = await put<Equipment>(`/equipment/${equipment.value.id}/status`, {
      status: isRunning ? 'maintenance' : 'running',
    })
    equipment.value = updated
    showToast(`${action}成功`)
  } finally {
    actionLoading.value = false
  }
}

function goEdit() {
  if (!equipment.value) return
  router.push(`/equipment/${equipment.value.id}/edit`)
}

onMounted(fetchDetail)
</script>

<template>
  <div class="equipment-detail">
    <van-nav-bar
      title="设备详情"
      left-arrow
      @click-left="router.back()"
    />

    <!-- Loading -->
    <div v-if="loading" class="loading-container">
      <van-loading type="spinner" size="24px">加载中...</van-loading>
    </div>

    <!-- Detail Content -->
    <template v-else-if="equipment">
      <!-- Basic Info Card -->
      <van-card
        :title="equipment.equipment_name"
        :desc="equipment.equipment_code"
      >
        <template #tags>
          <van-tag
            :type="statusTypes[equipment.status] || 'default'"
            size="medium"
          >
            {{ statusLabels[equipment.status] || equipment.status }}
          </van-tag>
        </template>
      </van-card>

      <!-- Detail Fields -->
      <van-cell-group title="基本信息" class="info-group">
        <van-cell title="设备编码" :value="equipment.equipment_code" />
        <van-cell title="设备名称" :value="equipment.equipment_name" />
        <van-cell title="规格型号" :value="equipment.model || '-'" />
        <van-cell title="生产厂家" :value="equipment.manufacturer || '-'" />
        <van-cell title="所在位置" :value="equipment.location || '-'" />
        <van-cell title="安装日期" :value="equipment.install_date || '-'" />
        <van-cell title="设备状态" :value="statusLabels[equipment.status] || equipment.status" />
        <van-cell title="创建时间" :value="equipment.created_at" />
        <van-cell title="更新时间" :value="equipment.updated_at" />
      </van-cell-group>

      <!-- Action Buttons -->
      <div class="action-buttons">
        <van-button
          type="primary"
          block
          class="action-btn"
          @click="goEdit"
        >
          编辑设备
        </van-button>
        <van-button
          :type="equipment.status === 'running' ? 'warning' : 'success'"
          block
          class="action-btn"
          :loading="actionLoading"
          :disabled="equipment.status === 'scrapped'"
          @click="toggleStatus"
        >
          {{ equipment.status === 'running' ? '停用设备' : '启用设备' }}
        </van-button>
      </div>
    </template>

    <!-- Not Found -->
    <van-empty v-else description="未找到设备信息" />
  </div>
</template>

<style scoped>
.equipment-detail {
  min-height: 100vh;
  background: #f7f8fa;
}

.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
}

.info-group {
  margin-top: 12px;
}

.action-buttons {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.action-btn {
  border-radius: 8px;
}
</style>
