<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse } from '@/types'

interface MaintenancePlan {
  id: number
  equipment_id: number
  equipment_name?: string
  plan_name: string
  plan_type: string
  cycle_value: number
  cycle_unit: string
  next_execute_at?: string
  status: string
}
interface Equipment { id: number; equipment_name: string }

const plans = ref<MaintenancePlan[]>([])
const loading = ref(false)
const showCreate = ref(false)
const equipments = ref<Equipment[]>([])
const form = ref({
  equipment_id: '' as string | number,
  plan_name: '',
  plan_type: '',
  cycle_value: 1,
  cycle_unit: 'month',
})
const submitting = ref(false)

async function loadData() {
  loading.value = true
  try {
    const r = await get<PaginatedResponse<MaintenancePlan>>('/maintenance-plans', {})
    plans.value = r.items || []
  } finally {
    loading.value = false
  }
}

async function loadEquipments() {
  try {
    const r = await get<PaginatedResponse<Equipment>>('/equipment', { page_size: 100 })
    equipments.value = r.items || []
  } catch { /* ignore */ }
}

async function handleCreate() {
  if (!form.value.equipment_id || !form.value.plan_name) {
    showToast('请选择设备并填写计划名称')
    return
  }
  submitting.value = true
  try {
    await post('/maintenance-plans', form.value)
    showToast('维护计划已创建')
    showCreate.value = false
    form.value = { equipment_id: '', plan_name: '', plan_type: '', cycle_value: 1, cycle_unit: 'month' }
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
      <van-button type="primary" size="small" @click="showCreate = true">新建维护计划</van-button>
    </div>

    <van-cell
      v-for="p in plans" :key="p.id"
      :title="`#${p.id} ${p.plan_name}`"
      :label="`${p.equipment_name || ''} | ${p.plan_type} | 周期 ${p.cycle_value}${p.cycle_unit}`"
      :value="p.status"
    />
    <van-empty v-if="!loading && plans.length === 0" description="暂无维护计划" />
    <van-loading v-if="loading" />

    <van-dialog v-model:show="showCreate" title="新建维护计划" show-cancel-button @confirm="handleCreate" :loading="submitting">
      <div style="padding:16px;">
        <van-field v-model="form.equipment_id" label="设备" placeholder="选择设备" :rules="[{required:true}]">
          <template #input>
            <van-picker
              :columns="equipments.map(e => ({ text: e.equipment_name, value: e.id }))"
              @confirm="(v:any) => form.equipment_id = v.value"
            />
          </template>
        </van-field>
        <van-field v-model="form.plan_name" label="计划名称" placeholder="如：月度保养" />
        <van-field v-model="form.plan_type" label="计划类型" placeholder="如：预防性" />
        <van-field v-model.number="form.cycle_value" label="周期值" type="digit" />
        <van-field v-model="form.cycle_unit" label="周期单位" placeholder="month/week" />
      </div>
    </van-dialog>
  </div>
</template>
