<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '@/api/client'
import { showToast } from 'vant'

const router = useRouter()
const form = ref({ wo_no: '', product_code: '', product_name: '', planned_qty: 0, remark: '' })
const submitting = ref(false)

async function handleSubmit() {
  submitting.value = true
  try {
    await post('/work-orders', form.value)
    showToast('创建成功')
    router.push('/work-orders')
  } catch { showToast('创建失败') }
  finally { submitting.value = false }
}
</script>

<template>
  <div>
    <van-nav-bar title="新建工单" left-arrow @click-left="router.back()" />
    <van-form @submit="handleSubmit" style="margin-top:16px">
      <van-field v-model="form.wo_no" label="工单号" placeholder="自动生成或手动输入" :rules="[{required:true}]" />
      <van-field v-model="form.product_code" label="产品编码" :rules="[{required:true}]" />
      <van-field v-model="form.product_name" label="产品名称" :rules="[{required:true}]" />
      <van-field v-model.number="form.planned_qty" label="计划数量" type="digit" :rules="[{required:true}]" />
      <van-field v-model="form.remark" label="备注" type="textarea" rows="3" />
      <div style="margin:16px"><van-button round block type="primary" native-type="submit" :loading="submitting">提交</van-button></div>
    </van-form>
  </div>
</template>
