<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import { showToast } from 'vant'

interface SystemModule {
  code: string
  name: string
  status: string
  routes?: string[]
}
interface SystemConfig {
  app_name?: string
  version?: string
  environment?: string
  debug?: boolean
  modules?: SystemModule[]
}

// 模块编码 → 前端导航路径（仅用于展示入口，启用状态以 API 为准）
const MODULE_PATHS: Record<string, string> = {
  M01: '/work-orders',
  M02: '/equipment',
  M03: '/quality',
  M04: '/andon',
  M05: '/andon',
  M07: '/dashboard',
  M08: '/dashboard',
  M09: '/dashboard',
  M10: '/basics/products',
  M11: '/energy',
  M12: '/data-collection',
  M20: '/wms/warehouse-tree',
  M16: '/trials',
}

const config = ref<SystemConfig>({})
const loading = ref(true)

async function loadConfig() {
  loading.value = true
  try {
    const res = await get<SystemConfig>('/system/config')
    config.value = res || {}
  } catch (e: any) {
    const code = e?.response?.data?.detail?.code
    if (code === 'MISSING_TOKEN' || code === '401-0002') {
      showToast('未授权，请确认已在 mfg 平台注册')
    }
    config.value = {}
  } finally {
    loading.value = false
  }
}

function isEnabled(m: SystemModule): boolean {
  return m.status === 'active' || m.status === 'enabled'
}

onMounted(loadConfig)
</script>

<template>
  <div>
    <van-cell-group title="系统信息">
      <van-cell title="应用名称" :value="config.app_name || '—'" />
      <van-cell title="版本" :value="config.version || '—'" />
      <van-cell title="运行环境" :value="config.environment || '—'" />
      <van-cell title="调试模式" :value="config.debug ? '开启' : '关闭'" />
    </van-cell-group>

    <van-cell-group title="模块状态（来自系统配置接口）" style="margin-top:16px;">
      <van-cell v-for="mod in (config.modules || [])" :key="mod.code">
        <template #title>
          <div style="display:flex; align-items:center; gap:8px;">
            <span>{{ mod.name }}</span>
            <van-tag :type="isEnabled(mod) ? 'success' : 'default'">
              {{ isEnabled(mod) ? '已启用' : '未启用' }}
            </van-tag>
            <span style="font-size:11px; color:var(--color-text-tertiary);">{{ mod.code }}</span>
          </div>
        </template>
        <template #value v-if="MODULE_PATHS[mod.code]">
          <router-link :to="MODULE_PATHS[mod.code]" style="color:var(--color-primary); font-size:13px;">
            进入
          </router-link>
        </template>
      </van-cell>
      <van-empty v-if="!loading && (!config.modules || config.modules.length === 0)" description="暂无模块数据" />
    </van-cell-group>

    <van-loading v-if="loading" style="margin-top:40px;" />
  </div>
</template>
