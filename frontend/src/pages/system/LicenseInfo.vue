<script setup lang="ts">
import { ref } from 'vue'
import { showToast } from 'vant'

interface License {
  tenant_id: string
  status: string
  expires_at: string
  modules: string[]
  api_key: string
  last_sync: string
}

const license = ref<License>({
  tenant_id: 'default',
  status: 'active',
  expires_at: '2027-06-15',
  modules: ['M01', 'M02', 'M03', 'M05', 'M11', 'M12'],
  api_key: 'ziwi_********...',
  last_sync: new Date().toISOString().split('T')[0],
})
</script>

<template>
  <div>
    <van-cell-group title="许可证信息">
      <van-cell title="租户" :value="license.tenant_id" />
      <van-cell title="状态">
        <template #value>
          <van-tag type="success">有效</van-tag>
        </template>
      </van-cell>
      <van-cell title="过期时间" :value="license.expires_at" />
      <van-cell title="已授权模块" :value="license.modules.join(', ')" />
      <van-cell title="同步 API Key" :value="license.api_key" />
      <van-cell title="最后同步" :value="license.last_sync" />
    </van-cell-group>

    <div style="margin-top:16px; padding:0 16px;">
      <van-button type="primary" block @click="showToast('续租功能开发中')">续租</van-button>
    </div>
  </div>
</template>
