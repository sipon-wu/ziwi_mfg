<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'

interface LicenseStatus {
  status: string
  message?: string
  tenant_id?: string
  expires_at?: string
  modules?: string[]
}

const license = ref<LicenseStatus | null>(null)
const loading = ref(true)
const error = ref(false)

async function loadLicense() {
  loading.value = true
  error.value = false
  try {
    const res = await get<LicenseStatus>('/system/license')
    license.value = res || { status: 'unknown' }
  } catch {
    error.value = true
    license.value = null
  } finally {
    loading.value = false
  }
}

onMounted(loadLicense)
</script>

<template>
  <div>
    <van-cell-group title="许可证信息">
      <van-cell title="状态">
        <template #value>
          <van-tag v-if="license && license.status === 'active'" type="success">有效</van-tag>
          <van-tag v-else-if="license && license.status === 'not_configured'" type="warning">未配置</van-tag>
          <van-tag v-else type="default">未知</van-tag>
        </template>
      </van-cell>
      <van-cell v-if="license && license.tenant_id" title="租户" :value="license.tenant_id" />
      <van-cell v-if="license && license.expires_at" title="过期时间" :value="license.expires_at" />
      <van-cell
        v-if="license && license.modules && license.modules.length"
        title="已授权模块"
        :value="license.modules.join(', ')"
      />
      <van-cell v-if="license && license.message" title="说明" :value="license.message" />
    </van-cell-group>

    <!-- 后端许可证模块尚未实现：展示真实占位，严禁返回假数据 -->
    <van-cell-group v-if="license && license.status !== 'active'" title="提示" style="margin-top:16px;">
      <van-cell>
        <template #title>
          <span style="color:var(--color-text-secondary); font-size:13px;">
            许可证管理模块待上线，当前暂无可展示的真实许可证数据。
          </span>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group v-if="error" title="提示" style="margin-top:16px;">
      <van-cell>
        <template #title>
          <span style="color:var(--color-text-secondary); font-size:13px;">
            许可证状态获取失败，请稍后重试。
          </span>
        </template>
      </van-cell>
    </van-cell-group>

    <div style="margin-top:16px; padding:0 16px;">
      <van-button type="primary" block :loading="loading" @click="loadLicense">刷新</van-button>
    </div>

    <van-loading v-if="loading" style="margin-top:40px;" />
  </div>
</template>
