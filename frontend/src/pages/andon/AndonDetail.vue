<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast, showConfirmDialog } from 'vant'
import type { AndonCall } from '@/types'

const route = useRoute()
const call = ref<AndonCall | null>(null)

async function fetch() {
  const res = await get<AndonCall>(`/andon/calls/${route.params.id}`)
  call.value = res
}

async function updateStatus(action: string) {
  const label = action === 'resolve' ? '解决' : action === 'respond' ? '响应' : '升级'
  showConfirmDialog({ title: '确认操作', message: `确定${label}此呼叫？` })
    .then(async () => {
      await post(`/andon/calls/${route.params.id}/action`, { action })
      showToast('操作成功')
      fetch()
    })
    .catch(() => {})
}

onMounted(fetch)
</script>

<template>
  <div v-if="call" style="padding:16px;">
    <van-cell-group title="呼叫信息">
      <van-cell title="呼叫编号" :value="call.call_no || '-'" />
      <van-cell title="呼叫类型" :value="call.call_type || '-'" />
      <van-cell title="优先级" :value="call.priority || '-'" />
      <van-cell title="状态" :value="call.status || '-'" />
      <van-cell title="呼叫时间" :value="call.created_at || '-'" />
    </van-cell-group>

    <div v-if="call.description" style="margin:12px 0; padding:12px; background:var(--color-background-secondary); border-radius:8px;">
      <p style="margin:0 0 4px; font-size:13px; color:var(--color-text-secondary);">描述</p>
      <p style="margin:0; font-size:13px;">{{ call.description }}</p>
    </div>

    <div style="display:flex; gap:8px; margin-top:16px; flex-wrap:wrap;">
      <van-button v-if="call.status === 'pending'" type="primary" size="small" @click="updateStatus('respond')">响应</van-button>
      <van-button v-if="call.status !== 'resolved'" type="success" size="small" @click="updateStatus('resolve')">解决</van-button>
      <van-button v-if="call.status === 'pending' || call.status === 'responding'" type="warning" size="small" @click="updateStatus('escalate')">升级</van-button>
    </div>
  </div>
  <van-empty v-else description="加载中..." />
</template>
