<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '@/api/client'
import { showToast } from 'vant'

const router = useRouter()
const submitting = ref(false)

const form = ref({
  qc_type: 'ipqc',
  order_no: '',
  product_name: '',
  inspector: '',
  remark: '',
})

const qcTypes = [
  { value: 'iqc', label: '来料检验' },
  { value: 'ipqc', label: '过程检验' },
  { value: 'fqc', label: '成品检验' },
  { value: 'oqc', label: '出货检验' },
]

async function onSubmit() {
  if (!form.value.order_no) {
    showToast('请填写检验单号')
    return
  }
  submitting.value = true
  try {
    await post('/inspection-orders', form.value)
    showToast('创建成功')
    router.push('/quality')
  } catch {
    showToast('创建失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div style="padding:16px;">
    <van-form @submit="onSubmit">
      <van-cell-group title="检验单信息">
        <van-field v-model="form.order_no" label="检验单号" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="form.product_name" label="产品名称" placeholder="选填" />
        <van-field name="qc_type" label="检验类型">
          <template #input>
            <van-radio-group v-model="form.qc_type" direction="horizontal">
              <van-radio v-for="t in qcTypes" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field v-model="form.inspector" label="检验员" placeholder="选填" />
        <van-field v-model="form.remark" label="备注" type="textarea" placeholder="选填" />
      </van-cell-group>
      <div style="margin:16px;">
        <van-button type="primary" block native-type="submit" :loading="submitting">创建检验单</van-button>
      </div>
    </van-form>
  </div>
</template>
