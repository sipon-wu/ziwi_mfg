<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

interface RouteItem {
  id: number
  code: string
  name: string
  version: number
  status: string
  route_type: string
  effective_from: string | null
  effective_to: string | null
  description: string | null
  step_count: number
  created_at: string
  updated_at: string
  published_at: string | null
}

const router = useRouter()
const rawList = ref<RouteItem[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const showEditDialog = ref(false)
const editing = ref<Partial<RouteItem>>({})
const isEdit = ref(false)

// 高级检索 + 行展开
const cfg = getSearchConfig('routes')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<RouteItem>(cfg)
const list = computed<RouteItem[]>(() =>
  conditions.value.length ? applyFilter(rawList.value) : rawList.value,
)
const showSearch = ref(false)
const expandedId = ref<number | null>(null)
function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}
function onSearchSubmit(c: SearchCondition[]) {
  conditions.value = c
  showSearch.value = false
}
function onResetSubmit() {
  conditions.value = []
  showSearch.value = false
}
function condText(c: SearchCondition) {
  return describeCondition(c, cfg)
}

const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'published', label: '已发布', color: 'success' },
  { value: 'archived', label: '已归档', color: 'warning' },
]
const ROUTE_TYPE_OPTIONS = [
  { value: 'discrete', label: '离散制造' },
  { value: 'process', label: '流程制造' },
]

function statusLabel(v: string): string {
  return STATUS_OPTIONS.find(o => o.value === v)?.label || v
}
function statusColor(v: string): string {
  return STATUS_OPTIONS.find(o => o.value === v)?.color || 'default'
}
function routeTypeLabel(v: string): string {
  return ROUTE_TYPE_OPTIONS.find(o => o.value === v)?.label || v
}

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: 1, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await get('/routes', { params })
    rawList.value = res.items || []
  } catch (e: any) {
    showToast(e?.detail?.message || '获取工艺路线列表失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  fetchData()
}

function onReset() {
  keyword.value = ''
  statusFilter.value = ''
  onSearch()
}

function openCreate() {
  isEdit.value = false
  editing.value = {
    code: '',
    name: '',
    route_type: 'discrete',
    effective_from: null,
    effective_to: null,
    description: null,
  }
  showEditDialog.value = true
}

function openEdit(item: RouteItem) {
  if (item.status !== 'draft') {
    showToast('仅草稿可编辑')
    return
  }
  isEdit.value = true
  editing.value = { ...item }
  showEditDialog.value = true
}

async function handleSave() {
  try {
    const data = { ...editing.value }
    if (isEdit.value) {
      await put(`/routes/${data.id}`, data)
      showToast('更新成功')
    } else {
      await post('/routes', data)
      showToast('创建成功')
    }
    showEditDialog.value = false
    page.value = 1
    fetchData()
  } catch (e: any) {
    showToast(e?.detail?.message || '操作失败')
  }
}

async function handlePublish(item: RouteItem) {
  showDialog({
    title: '确认发布',
    message: `发布后不可再编辑路线「${item.code} V${item.version}」，确认发布？`,
    showCancelButton: true,
  }).then(async (action: string) => {
    if (action === 'confirm') {
      try {
        await post(`/routes/${item.id}/publish`)
        showToast('已发布')
        fetchData()
      } catch (e: any) {
        showToast(e?.detail?.message || '发布失败')
      }
    }
  })
}

async function handleArchive(item: RouteItem) {
  showDialog({
    title: '确认归档',
    message: `确定归档路线「${item.code} V${item.version}」？`,
    showCancelButton: true,
  }).then(async (action: string) => {
    if (action === 'confirm') {
      try {
        await post(`/routes/${item.id}/archive`)
        showToast('已归档')
        fetchData()
      } catch (e: any) {
        showToast(e?.detail?.message || '归档失败')
      }
    }
  })
}

async function handleNewVersion(item: RouteItem) {
  try {
    const res = await post(`/routes/${item.id}/new-version`)
    showToast(`已创建 V${res.version}`)
    fetchData()
  } catch (e: any) {
    showToast(e?.detail?.message || '创建新版本失败')
  }
}

async function handleDelete(item: RouteItem) {
  if (item.status !== 'draft') {
    showToast('仅草稿可删除')
    return
  }
  showDialog({
    title: '确认删除',
    message: `确定删除路线「${item.code} V${item.version}」？步骤将一并删除。`,
    showCancelButton: true,
  }).then(async (action: string) => {
    if (action === 'confirm') {
      try {
        await del(`/routes/${item.id}`)
        showToast('删除成功')
        page.value = 1
        fetchData()
      } catch (e: any) {
        showToast(e?.detail?.message || '删除失败')
      }
    }
  })
}

function goEditor(item: RouteItem) {
  router.push(`/basics/route-editor/${item.id}`)
}

onMounted(fetchData)
</script>

<template>
  <div class="p-4">
    <!-- 搜索栏 -->
    <div class="flex flex-wrap gap-3 mb-4 items-end">
      <div class="flex-1 min-w-[200px]">
        <van-field
          v-model="keyword"
          placeholder="搜索路线编码/名称"
          clearable
          @keyup.enter="onSearch"
        />
      </div>
      <div class="w-36">
        <SelectField v-model="statusFilter" :options="STATUS_OPTIONS" placeholder="状态" clearable />
      </div>
      <div class="flex gap-2">
        <van-button type="primary" size="small" @click="onSearch">搜索</van-button>
        <van-button plain size="small" @click="onReset">重置</van-button>
        <van-button type="success" size="small" @click="openCreate">新建路线</van-button>
        <van-button size="small" icon="filter-o" @click="showSearch = true">高级检索</van-button>
      </div>
    </div>

    <!-- 高级检索条件 chips -->
    <div v-if="conditions.length" class="flex flex-wrap gap-2 mb-3 px-1">
      <van-tag
        v-for="c in conditions"
        :key="c.uid"
        type="primary"
        closeable
        size="medium"
        @close="removeCondition(c.uid)"
      >{{ condText(c) }}</van-tag>
      <van-button size="mini" plain type="primary" @click="onResetSubmit">清空</van-button>
    </div>

    <!-- 列表 -->
    <div v-if="loading" class="text-center py-10 text-gray-400">加载中...</div>
    <div v-else-if="list.length === 0" class="text-center py-10 text-gray-400">暂无数据</div>
    <van-cell-group v-else>
      <van-cell
        v-for="item in list"
        :key="item.id"
        @click="goEditor(item)"
        is-link
      >
        <template #title>
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-medium">{{ item.code }}</span>
            <van-tag :type="statusColor(item.status)" size="small">{{ statusLabel(item.status) }}</van-tag>
            <van-tag plain size="small">V{{ item.version }}</van-tag>
            <van-tag plain size="small">{{ routeTypeLabel(item.route_type) }}</van-tag>
          </div>
          <div class="text-sm text-gray-500 mt-1">{{ item.name }}</div>
        </template>
        <template #label>
          <div class="text-xs text-gray-400 mt-1">
            工序步骤: {{ item.step_count }} 道
            <span v-if="item.published_at"> | 发布于 {{ item.published_at?.slice(0, 10) }}</span>
          </div>
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #right-icon>
          <div class="flex gap-1" @click.stop>
            <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="small" plain @click.stop="toggleExpand(item.id)" />
            <van-button
              v-if="item.status === 'draft'"
              icon="edit" size="small" type="primary" plain
              @click="openEdit(item)"
            />
            <van-button
              v-if="item.status === 'draft'"
              icon="success" size="small" type="success" plain
              @click="handlePublish(item)"
            />
            <van-button
              v-if="item.status === 'published'"
              icon="records" size="small" type="warning" plain
              @click="handleNewVersion(item)"
            />
            <van-button
              v-if="item.status !== 'archived'"
              icon="folder" size="small" plain
              @click="handleArchive(item)"
            />
            <van-button
              v-if="item.status === 'draft'"
              icon="delete" size="small" type="danger" plain
              @click="handleDelete(item)"
            />
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <!-- 创建/编辑弹窗 -->
    <van-dialog
      v-model:show="showEditDialog"
      :title="isEdit ? '编辑工艺路线' : '新增工艺路线'"
      show-cancel-button
      @confirm="handleSave"
      class="!w-[500px]"
    >
      <div class="p-4 space-y-3">
        <van-field v-model="editing.code" label="路线编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="路线名称" required placeholder="请输入名称" />
        <van-field label="路线类型" required>
          <template #input>
            <SelectField v-model="editing.route_type" :options="ROUTE_TYPE_OPTIONS" class="w-full" />
          </template>
        </van-field>
        <van-field label="生效日期" @click="showDateFrom = true">
          <template #input>
            <span v-if="editing.effective_from" class="text-sm">{{ editing.effective_from }}</span>
            <span v-else class="text-sm text-gray-400">可选</span>
          </template>
        </van-field>
        <van-field label="失效日期" @click="showDateTo = true">
          <template #input>
            <span v-if="editing.effective_to" class="text-sm">{{ editing.effective_to }}</span>
            <span v-else class="text-sm text-gray-400">可选</span>
          </template>
        </van-field>
        <van-field v-model="editing.description" label="描述" type="textarea" rows="2" placeholder="可选" />
      </div>
    </van-dialog>

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>
