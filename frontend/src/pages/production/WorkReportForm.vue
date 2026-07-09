<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import dayjs from 'dayjs'

const router = useRouter()
const form = ref({
  work_order_id: '' as string, report_date: dayjs().format('YYYY-MM-DD'),
  operation_code: '', operation_name: '', input_qty: 0, output_qty: 0,
  scrap_qty: 0, defect_reason: '', labor_hours: 0, machine_hours: 0,
})
const orders = ref<WorkOrder[]>([])
const submitting = ref(false)

onMounted(async () => {
  try { const r = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 100 }); orders.value = r.items || [] }
  catch (e) { console.warn('[WorkReportForm] 获取工单列表失败', e) }
})

async function handleSubmit() {
  submitting.value = true
  try {
    await post('/work-reports', form.value)
    showToast('报工提交成功')
    router.push('/work-reports')
  } catch { showToast('提交失败') }
  finally { submitting.value = false }
}
</script>

<template>
  <div>
    <van-nav-bar title="个人报工" left-arrow @click-left="router.back()" />
    <van-form @submit="handleSubmit" style="margin-top:16px">
      <van-field v-model="form.work_order_id" label="工单" placeholder="选择工单" :rules="[{required:true}]">
        <template #input>
          <van-picker :columns="orders.map(o => ({ text: `${o.wo_no} - ${o.product_name}`, value: o.id }))" @confirm="(v:any) => form.work_order_id = v.value" />
        </template>
      </van-field>
      <van-field v-model="form.report_date" label="报工日期" type="date" :rules="[{required:true}]" />
      <van-field v-model="form.operation_code" label="工序编码" />
      <van-field v-model="form.operation_name" label="工序名称" />
      <van-field v-model.number="form.output_qty" label="合格数量" type="digit" :rules="[{required:true}]" />
      <van-field v-model.number="form.scrap_qty" label="不良数量" type="digit" />
      <van-field v-model="form.defect_reason" label="不良原因" placeholder="如有不良请填写原因" />
      <van-field v-model.number="form.labor_hours" label="工时(小时)" type="digit" />
      <div style="margin:16px"><van-button round block type="primary" native-type="submit" :loading="submitting">提交报工</van-button></div>
    </van-form>
  </div>
</template>
