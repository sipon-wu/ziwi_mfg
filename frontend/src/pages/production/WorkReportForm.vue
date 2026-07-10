<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import dayjs from 'dayjs'
import type { WorkOrder, PaginatedResponse } from '@/types'

const router = useRouter()

const DEFECT_REASONS = ['尺寸超差', '表面缺陷', '装配不良', '材料问题', '设备异常', '其他']
const REPORT_MODES = [
  { value: 'personal', label: '个人报工' },
  { value: 'team', label: '小组报工' },
  { value: 'equipment', label: '设备报工' },
]

const form = ref({
  report_mode: 'personal',
  work_order_id: '' as string | number,
  report_date: dayjs().format('YYYY-MM-DD'),
  operation_code: '',
  operation_name: '',
  input_qty: 0,
  output_qty: 0,
  scrap_qty: 0,
  defect_reasons: [] as string[],
  defect_reason: '',
  labor_hours: 0,
  machine_hours: 0,
  start_time: '',
  end_time: '',
  unit_price: 0,
})
const orders = ref<WorkOrder[]>([])
const submitting = ref(false)

// 工价自动计算（前端计算展示；有工价接口时再对接）
const total_price = computed(() => {
  const qty = Number(form.value.output_qty) || 0
  const price = Number(form.value.unit_price) || 0
  return Math.round(qty * price * 100) / 100
})

onMounted(async () => {
  try {
    const r = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 100 })
    orders.value = r.items || []
  } catch (e) {
    console.warn('[WorkReportForm] 获取工单列表失败', e)
  }
})

async function handleSubmit() {
  if (!form.value.work_order_id) {
    showToast('请先选择工单')
    return
  }
  const payload = {
    ...form.value,
    defect_reason: [...form.value.defect_reasons].join('、') || form.value.defect_reason || '',
    start_time: form.value.start_time || null,
    end_time: form.value.end_time || null,
  }
  submitting.value = true
  try {
    await post('/work-reports', payload)
    showToast('报工提交成功')
    router.push('/work-reports')
  } catch {
    showToast('提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <van-nav-bar title="报工录入" left-arrow @click-left="router.back()" />

    <van-form @submit="handleSubmit" style="margin-top:16px">
      <!-- 报工模式切换 -->
      <van-cell-group title="报工模式">
        <van-field name="report_mode">
          <template #input>
            <van-radio-group v-model="form.report_mode" direction="horizontal">
              <van-radio v-for="m in REPORT_MODES" :key="m.value" :name="m.value">{{ m.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
      </van-cell-group>

      <van-cell-group title="报工明细" style="margin-top:12px;">
        <van-field v-model="form.work_order_id" label="工单" placeholder="选择工单" :rules="[{required:true}]">
          <template #input>
            <van-picker
              :columns="orders.map(o => ({ text: `${o.wo_no} - ${o.product_name}`, value: o.id }))"
              @confirm="(v:any) => form.work_order_id = v.value"
            />
          </template>
        </van-field>
        <van-field v-model="form.report_date" label="报工日期" type="date" :rules="[{required:true}]" />
        <van-field v-model="form.operation_code" label="工序编码" />
        <van-field v-model="form.operation_name" label="工序名称" />
        <van-field v-model.number="form.input_qty" label="投入数量" type="digit" />
        <van-field v-model.number="form.output_qty" label="合格数量" type="digit" :rules="[{required:true}]" />
        <van-field v-model.number="form.scrap_qty" label="不良数量" type="digit" />
      </van-cell-group>

      <!-- 不良原因选择 -->
      <van-cell-group title="不良原因（可多选）" style="margin-top:12px;">
        <van-field name="defect_reasons">
          <template #input>
            <van-checkbox-group v-model="form.defect_reasons" direction="horizontal">
              <van-checkbox v-for="r in DEFECT_REASONS" :key="r" :name="r" shape="square">{{ r }}</van-checkbox>
            </van-checkbox-group>
          </template>
        </van-field>
      </van-cell-group>

      <!-- 打卡时间 -->
      <van-cell-group title="打卡时间" style="margin-top:12px;">
        <van-field v-model="form.start_time" label="开始时间" type="time" placeholder="HH:mm" />
        <van-field v-model="form.end_time" label="结束时间" type="time" placeholder="HH:mm" />
      </van-cell-group>

      <!-- 工价自动计算 -->
      <van-cell-group title="工价" style="margin-top:12px;">
        <van-field v-model.number="form.unit_price" label="工价(元/件)" type="digit" placeholder="0" />
        <van-cell title="应计工价" :value="`¥ ${total_price}`" />
      </van-cell-group>

      <van-cell-group title="工时" style="margin-top:12px;">
        <van-field v-model.number="form.labor_hours" label="工时(小时)" type="digit" />
        <van-field v-model.number="form.machine_hours" label="机时(小时)" type="digit" />
      </van-cell-group>

      <div style="margin:16px">
        <van-button round block type="primary" native-type="submit" :loading="submitting">提交报工</van-button>
      </div>
    </van-form>
  </div>
</template>
