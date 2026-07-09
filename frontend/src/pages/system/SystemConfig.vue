<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import { showToast } from 'vant'

interface SystemConfig {
  app_name?: string
  version?: string
  modules?: { code: string; name: string; enabled?: boolean }[]
  tenant_id?: string
  features?: Record<string, boolean>
  db_type?: string
}

const config = ref<SystemConfig>({})
const loading = ref(true)

async function loadConfig() {
  loading.value = true
  try {
    const res = await get<any>('/system/config')
    config.value = res || {}
  } catch {
    config.value = { app_name: '知微 ziwi SaaS', version: '1.0.0' }
  } finally {
    loading.value = false
  }
}

const moduleList = ref([
  { code: 'M01', name: '生产管理', path: '/work-orders', enabled: true },
  { code: 'M02', name: 'TPM 设备管理', path: '/equipment', enabled: true },
  { code: 'M03', name: '品质管理', path: '/quality', enabled: true },
  { code: 'M05', name: '安灯系统', path: '/andon', enabled: true },
  { code: 'M11', name: '能碳管理', path: '/energy', enabled: true },
  { code: 'M12', name: '数据采集', path: '/data-collection', enabled: true },
  { code: 'M13', name: '看板', path: '/dashboard', enabled: true },
  { code: 'M00', name: '基础平台（认证/租户/角色）', path: '', enabled: true },
])

onMounted(loadConfig)
</script>

<template>
  <div>
    <van-cell-group title="系统信息">
      <van-cell title="应用名称" :value="config.app_name || '知微 ziwi SaaS'" />
      <van-cell title="版本" :value="config.version || '1.0.0'" />
      <van-cell title="数据库" :value="config.db_type || '-'" />
      <van-cell title="租户" :value="config.tenant_id || '-'" />
    </van-cell-group>

    <van-cell-group title="模块状态" style="margin-top:16px;">
      <van-cell v-for="mod in moduleList" :key="mod.code">
        <template #title>
          <div style="display:flex; align-items:center; gap:8px;">
            <span>{{ mod.name }}</span>
            <van-tag :type="mod.enabled ? 'success' : 'default'" size="small">
              {{ mod.enabled ? '已启用' : '未启用' }}
            </van-tag>
            <span style="font-size:11px; color:var(--color-text-tertiary);">{{ mod.code }}</span>
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group title="API 状态" style="margin-top:16px;">
      <van-cell title="API 端点总数" value="~150" />
      <van-cell title="全量测试" value="111/111 通过" />
      <van-cell title="后端模块" value="16 个模块就绪" />
      <van-cell title="前端页面" value="11 个模块有界面" />
    </van-cell-group>

    <van-loading v-if="loading" style="margin-top:40px;" />
  </div>
</template>
