<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del, errorText } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import { useStatusTag } from '@/composables/useStatusTag'

interface Count { id: number; count_no: string; count_type: string; status: string; warehouse_id: number; warehouse_name: string; count_date: string; total_items: number; counted_items: number; diff_items: number; created_at: string }

/** 状态标签：文案/图标/语义统一取自 config/statusDict.ts（UE §1.2 双编码） */
const statusTagCache = new Map<string, ReturnType<typeof useStatusTag>>()
function statusTagOf(code: string): ReturnType<typeof useStatusTag> {
  let tag = statusTagCache.get(code)
  if (!tag) {
    tag = useStatusTag('wms_count', code)
    statusTagCache.set(code, tag)
  }
  return tag
}

const list = ref<Count[]>([])
const loading = ref(false)
const keyword = ref('')
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20

const statusOpts = [{ value: 'draft', label: '草稿' }, { value: 'in_progress', label: '盘点中' }, { value: 'completed', label: '已完成' }, { value: 'adjusted', label: '已调整' }, { value: 'closed', label: '已关闭' }]

const loadFailed = ref(false)
const loadErrorMessage = ref('')
const loadErrorKind = ref<'network' | 'business'>('business')

/** 加载/空/失败三分（UE-09/12）：失败不再伪装成空态 */
const listState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (list.value.length > 0) return 'ready'
  return !!(keyword.value || status.value) ? 'empty-filtered' : 'empty-true'
})

async function loadData() {
  loading.value = true
  loadFailed.value = false
  try {
    const res = await get<PaginatedResponse<Count>>('/wms/inventory-counts', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, status: status.value || undefined })
    list.value = res.items as Count[]
    total.value = res.total
  } catch (e) {
    // 加载失败必须说出来：此前无 catch，网络断了页面显示「暂无数据」，
    // 车间会以为真的没数据而重复建单
    loadFailed.value = true
    loadErrorMessage.value = errorText(e, '加载失败，请重试')
    loadErrorKind.value = (e as { response?: unknown })?.response ? 'business' : 'network'
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="盘点管理" right-text="新增盘点" @click-right="$router.push('/wms/inventory-counts/create')" />
    <van-search v-model="keyword" placeholder="搜索盘点单号" @search="onSearch" />
    <van-cell-group inset style="margin:8px">
      <van-tabs v-model:active="status" @change="onSearch" animated>
        <van-tab title="全部" name="" />
        <van-tab v-for="s in statusOpts" :key="s.value" :title="s.label" :name="s.value" />
      </van-tabs>
    </van-cell-group>

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id" is-link :to="`/wms/inventory-counts/${item.id}`">
        <template #title>
          {{ item.count_no }}
          <span class="ziwi-state" :class="`ziwi-state--${statusTagOf(item.status).semantic.value}`" style="margin-right:6px">
            <van-icon :name="statusTagOf(item.status).icon.value" />
            {{ statusTagOf(item.status).label.value }}
          </span>
        </template>
        <template #label>
          <div>类型: {{ item.count_type === 'full' ? '全盘' : item.count_type === 'cycle' ? '循环盘点' : '抽盘' }} | 仓库: {{ item.warehouse_name }}</div>
          <div>盘点日期: {{ item.count_date }} | 总物料: {{ item.total_items }}</div>
          <div>已盘: {{ item.counted_items }} | 差异: {{ item.diff_items }}</div>
        </template>
      </van-cell>
    </van-list>
    <ZiwiStateView
      v-if="listState !== 'ready'"
      :state="listState"
      object-name="盘点单"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      @retry="loadData"
    />
  </div>
</template>
