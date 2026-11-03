<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { get, errorText } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiListToolbar from '@/components/ziwi/ZiwiListToolbar.vue'
import { useStatusTag } from '@/composables/useStatusTag'

interface Batch { id: number; batch_no: string; material_id: number; material_code: string; material_name: string; supplier_batch_no: string; manufacture_date: string; expiry_date: string; status: string; is_locked: boolean }

/** 状态标签：文案/图标/语义统一取自 config/statusDict.ts（UE §1.2 双编码） */
const statusTagCache = new Map<string, ReturnType<typeof useStatusTag>>()
function statusTagOf(code: string): ReturnType<typeof useStatusTag> {
  let tag = statusTagCache.get(code)
  if (!tag) {
    tag = useStatusTag('wms_batch', code)
    statusTagCache.set(code, tag)
  }
  return tag
}

const list = ref<Batch[]>([])
const loading = ref(false)
const keyword = ref('')
const materialId = ref<number | undefined>()
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20


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
    const res = await get<PaginatedResponse<Batch>>('/wms/batches', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, material_id: materialId.value || undefined, status: status.value || undefined })
    list.value = res.items as Batch[]
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
/** 重置：清空关键词与条件后回到第一页（工具栏「重置」不是只清输入框） */
function onReset() { keyword.value = ''; status.value = ''; materialId.value = undefined; onSearch() }

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="批次管理" />
    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索批次号/供应商批号"
      :loading="loading"
      :show-advanced="false"
      @search="onSearch"
      @reset="onReset"
    />

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          {{ item.batch_no }}
          <span class="ziwi-state" :class="`ziwi-state--${statusTagOf(item.status).semantic.value}`" style="margin-right:6px">
            <van-icon :name="statusTagOf(item.status).icon.value" />
            {{ statusTagOf(item.status).label.value }}
          </span>
        </template>
        <template #label>
          <div>物料: {{ item.material_code }} - {{ item.material_name }}</div>
          <div v-if="item.supplier_batch_no">供应商批号: {{ item.supplier_batch_no }}</div>
          <div v-if="item.manufacture_date">生产日期: {{ item.manufacture_date }}</div>
          <div v-if="item.expiry_date">到期日: {{ item.expiry_date }}</div>
        </template>
        <template #value>
          <van-icon v-if="item.is_locked" name="lock" color="red" />
        </template>
      </van-cell>
    </van-list>
    <ZiwiStateView
      v-if="listState !== 'ready'"
      :state="listState"
      object-name="批次记录"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      @retry="loadData"
    />
  </div>
</template>
