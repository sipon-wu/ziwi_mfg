<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast } from 'vant'
import { createTrial } from '@/api/trial'

const router = useRouter()

const form = ref({
  trial_type: '',
  product_name: '',
  product_spec: '',
  product_id: null as number | null,
  planned_qty: null as number | null,
  priority: 500,
  lab_required: false,
  scheme_json: null as any,
  target_json: null as any,
  key_params: null as any,
})

const typeOptions = [
  { value: 'new_product', label: '新产品试产 - 全新产品的首次试制' },
  { value: 'new_process', label: '新工艺试产 - 已有产品采用新工艺' },
  { value: 'new_material', label: '新材料试产 - 使用替代材料' },
  { value: 'eco_verification', label: '工程变更验证 - ECO/ECN变更后验证' },
  { value: 'tooling_trial', label: '模具/工装验证 - 新模具首件验证' },
]

const schemeText = ref('')
const targetText = ref('')

async function handleSubmit() {
  if (!form.value.trial_type) { showToast('请选择试产类型'); return }
  if (!form.value.product_name) { showToast('请输入产品名称'); return }

  // 解析 JSON 字段
  if (schemeText.value) {
    try { form.value.scheme_json = JSON.parse(schemeText.value) }
    catch { showToast('试产方案JSON格式错误'); return }
  }
  if (targetText.value) {
    try { form.value.target_json = JSON.parse(targetText.value) }
    catch { showToast('预期目标JSON格式错误'); return }
  }

  showLoadingToast({ message: '创建中...', forbidClick: true })
  try {
    const data: any = { ...form.value }
    // 清理空字段
    if (!data.product_id) delete data.product_id
    if (!data.planned_qty) delete data.planned_qty
    if (!data.product_spec) delete data.product_spec

    const result = await createTrial(data) as any
    closeToast()
    showToast('创建成功')
    router.push(`/trials/${result.id}`)
  } catch {
    closeToast()
    showToast('创建失败')
  }
}

function goBack() { router.push('/trials') }
</script>

<template>
  <div>
    <van-nav-bar title="新建试产工单" left-arrow @click-left="goBack" />

    <van-form @submit="handleSubmit">
      <van-cell-group title="试产类型">
        <van-radio-group v-model="form.trial_type" direction="vertical" style="padding: 12px">
          <van-radio v-for="opt in typeOptions" :key="opt.value" :name="opt.value" style="margin-bottom: 8px">
            <span style="font-size: 13px">{{ opt.label }}</span>
          </van-radio>
        </van-radio-group>
      </van-cell-group>

      <van-cell-group title="产品信息">
        <van-field v-model="form.product_name" label="产品名称" placeholder="输入产品名称" required :rules="[{ required: true, message: '请输入产品名称' }]" />
        <van-field v-model="form.product_spec" label="产品规格" placeholder="产品规格/型号" />
        <van-field v-model="form.planned_qty" label="计划数量" placeholder="试产数量" type="digit" />
      </van-cell-group>

      <van-cell-group title="试产配置">
        <van-field name="priority" label="优先级">
          <template #input>
            <van-slider v-model="form.priority" :min="1" :max="1000" :step="10" style="width: 200px" />
          </template>
          <template #extra>
            <span style="font-size: 12px; color: #999">{{ form.priority }}</span>
          </template>
        </van-field>
        <van-cell center title="需要实验室检测">
          <template #right-icon>
            <van-switch v-model="form.lab_required" size="24" />
          </template>
        </van-cell>
      </van-cell-group>

      <van-cell-group title="试产方案 (JSON)">
        <van-field v-model="schemeText" type="textarea" rows="6" placeholder='{"key": "value"}' autosize />
      </van-cell-group>

      <van-cell-group title="预期目标 (JSON)">
        <van-field v-model="targetText" type="textarea" rows="6" placeholder='{"目标": "描述"}' autosize />
      </van-cell-group>

      <div style="padding: 16px">
        <van-button block type="primary" native-type="submit">创建试产工单</van-button>
      </div>
    </van-form>
  </div>
</template>
