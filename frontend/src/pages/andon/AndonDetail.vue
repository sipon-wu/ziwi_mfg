<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post, errorText } from '@/api/client'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import { showToast, showConfirmDialog } from 'vant'
import type { AndonCall } from '@/types'
import { enumLabel } from '@/config/enums'
import { statusTagOf } from '@/composables/useStatusTag'

const route = useRoute()
const router = useRouter()

const call = ref<AndonCall | null>(null)
const loading = ref(false)

/**
 * 详情三分：加载中 / 不存在 / 已就绪。
 *
 * 原写法是「空态组件 + v-else + 描述「加载中」」——`v-else` 同时兜住
 * "还在加载"和"查无此单"两种情况，且渲染的是**空态插画**，用户看到的是
 * 一张"什么都没有"的图配「加载中...」，会误判成单子不存在。
 */
const detailState = computed<StateKind>(() => {
  if (call.value) return 'ready'
  return loading.value ? 'loading' : 'empty-true'
})

async function fetch() {
  loading.value = true
  try {
    call.value = await get<AndonCall>(`/andon/calls/${route.params.id}`)
  } catch (e) {
    showToast(errorText(e, '安灯呼叫加载失败'))
  } finally {
    loading.value = false
  }
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
  <div v-if="call">
    <van-nav-bar title="安灯详情" left-arrow @click-left="() => router.push('/andon')" />
    <div style="padding:16px;">
      <van-cell-group title="呼叫信息">
        <van-cell title="呼叫编号" :value="call.call_no || '-'" />
        <van-cell title="呼叫类型" :value="enumLabel('call_type', call.call_type)" />
        <van-cell title="优先级" :value="enumLabel('priority', call.priority)" />
        <van-cell title="状态" :value="statusTagOf('andon_call', call.status).label" />
        <van-cell title="呼叫时间" :value="call.created_at || '-'" />
      </van-cell-group>

      <div v-if="call.description" style="margin:12px 0; padding:12px; background:var(--color-background-secondary); border-radius:8px;">
        <p style="margin:0 0 4px; font-size:13px; color:var(--color-text-secondary);">描述</p>
        <p style="margin:0; font-size:13px;">{{ call.description }}</p>
      </div>

      <div style="display:flex; gap:8px; margin-top:16px; flex-wrap:wrap;">
        <van-button v-if="call.status === 'pending'" type="primary" size="small" @click="updateStatus('respond')">响应</van-button>
        <van-button v-if="call.status !== 'resolved'" type="success" size="small" @click="updateStatus('resolve')">解决</van-button>
        <van-button v-if="call.status === 'pending' || call.status === 'in_progress'" type="warning" size="small" @click="updateStatus('escalate')">升级</van-button>
      </div>
    </div>
  </div>
  <ZiwiStateView v-else :state="detailState" skeleton="detail" object-name="安灯呼叫" />
</template>
