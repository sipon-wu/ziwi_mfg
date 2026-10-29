<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '@/api/client'
import { showToast } from 'vant'

const router = useRouter()
const submitting = ref(false)

// 对齐后端 CreateInspectionOrderRequest：order_type 必填（first/inspection/spot_check），
// 单号由后端自动生成（QC-YYYYMMDD-NNNN），无需手填。
const form = ref({
  order_type: 'inspection',
  remark: '',
})

const orderTypes = [
  { value: 'first', label: '首件检验' },
  { value: 'inspection', label: '过程检验' },
  { value: 'spot_check', label: '抽检' },
]

async function onSubmit() {
  submitting.value = true
  try {
    await post('/inspection-orders', form.value)
    showToast('创建成功')
    router.push('/quality')
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '创建失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div style="padding:16px;">
    <van-form @submit="onSubmit">
      <van-cell-group title="检验单信息（单号自动生成）">
        <van-field name="order_type" label="检验类型">
          <template #input>
            <van-radio-group v-model="form.order_type" direction="horizontal">
              <van-radio v-for="t in orderTypes" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field v-model="form.remark" label="备注" type="textarea" placeholder="选填" />
      </van-cell-group>
      <div style="margin:16px;">
        <van-button type="primary" block native-type="submit" :loading="submitting">创建检验单</van-button>
      </div>
    </van-form>
  </div>
</template>
