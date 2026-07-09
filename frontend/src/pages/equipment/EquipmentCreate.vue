<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '@/api/client'
import { showToast } from 'vant'

const router = useRouter()
const submitting = ref(false)

const form = ref({
  equipment_code: '',
  equipment_name: '',
  category_id: null as number | null,
  model: '',
  manufacturer: '',
  location: '',
  status: 'running',
})

async function onSubmit() {
  if (!form.value.equipment_code || !form.value.equipment_name) {
    showToast('请填写设备编码和名称')
    return
  }
  submitting.value = true
  try {
    await post('/equipment', form.value)
    showToast('创建成功')
    router.push('/equipment')
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
      <van-cell-group title="基本信息">
        <van-field v-model="form.equipment_code" label="设备编码" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="form.equipment_name" label="设备名称" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="form.model" label="型号" placeholder="选填" />
        <van-field v-model="form.manufacturer" label="制造商" placeholder="选填" />
        <van-field v-model="form.location" label="位置" placeholder="选填" />
      </van-cell-group>
      <div style="margin:16px;">
        <van-button type="primary" block native-type="submit" :loading="submitting">保存</van-button>
      </div>
    </van-form>
  </div>
</template>
