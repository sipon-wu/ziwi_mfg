<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import { usePagination } from '@/composables/usePagination'
import type { PaginatedResponse } from '@/types'

interface MaintenanceTask {
  id: number
  equipment_id: number
  equipment_name?: string
  task_type: string
  description: string
  priority: number
  status: string
}
interface Equipment { id: number; equipment_name: string }

const tasks = ref<MaintenanceTask[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()

const showCreate = ref(false)
const equipments = ref<Equipment[]>([])
const form = ref({
  equipment_id: '' as string | number,
  task_type: '',
  description: '',
  priority: 0,
})
const submitting = ref(false)

async function loadData() {
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<MaintenanceTask>>('/maintenance-tasks', { ...p })
  })
  tasks.value = items as MaintenanceTask[]
}

async function loadEquipments() {
  try {
    const r = await get<PaginatedResponse<Equipment>>('/equipment', { page_size: 100 })
    equipments.value = r.items || []
  } catch { /* ignore */ }
}

async function handleCreate() {
  if (!form.value.equipment_id || !form.value.task_type) {
    showToast('请选择设备并填写任务类型')
    return
  }
  submitting.value = true
  try {
    await post('/maintenance-tasks', form.value)
    showToast('保养任务已创建')
    showCreate.value = false
    form.value = { equipment_id: '', task_type: '', description: '', priority: 0 }
    resetPage()
    await loadData()
  } catch {
    showToast('创建失败')
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadData()
  loadEquipments()
})
</script>

<template>
  <div>
    <div style="padding:12px 16px;">
      <van-button type="primary" size="small" @click="showCreate = true">新建保养任务</van-button>
    </div>

    <van-list v-model:loading="loading" :finished="!total || tasks.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell
        v-for="t in tasks" :key="t.id"
        :title="`#${t.id} ${t.task_type}`"
        :label="(t.equipment_name || '') + ' | ' + (t.description || '')"
        :value="t.status"
      />
    </van-list>
    <van-empty v-if="!loading && tasks.length === 0" description="暂无保养任务" />

    <van-dialog v-model:show="showCreate" title="新建保养任务" show-cancel-button @confirm="handleCreate" :loading="submitting">
      <div style="padding:16px;">
        <van-field v-model="form.equipment_id" label="设备" placeholder="选择设备" :rules="[{required:true}]">
          <template #input>
            <van-picker
              :columns="equipments.map(e => ({ text: e.equipment_name, value: e.id }))"
              @confirm="(v:any) => form.equipment_id = v.value"
            />
          </template>
        </van-field>
        <van-field v-model="form.task_type" label="任务类型" placeholder="如：日常点检" />
        <van-field v-model="form.description" label="描述" type="textarea" rows="2" />
        <van-field v-model.number="form.priority" label="优先级" type="digit" />
      </div>
    </van-dialog>
  </div>
</template>
