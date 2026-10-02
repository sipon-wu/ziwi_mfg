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

// 高级检索 + 行展开（并集方式多列并排）
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
    <div v-else class="route-table-wrap">
      <table class="route-table">
        <thead>
          <tr>
            <th>路线编码</th>
            <th>路线名称</th>
            <th class="num">版本</th>
            <th>状态</th>
            <th>路线类型</th>
            <th class="num">步骤数</th>
            <th class="op">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="item in list" :key="item.id">
            <tr @click="toggleExpand(item.id)">
              <td>{{ item.code }}</td>
              <td>{{ item.name }}</td>
              <td class="num">V{{ item.version }}</td>
              <td>
                <van-tag :type="statusColor(item.status)" size="small">{{ statusLabel(item.status) }}</van-tag>
              </td>
              <td>{{ routeTypeLabel(item.route_type) }}</td>
              <td class="num">{{ item.step_count }}</td>
              <td class="op">
                <div class="op-btns">
                  <van-button
                    :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'"
                    size="mini"
                    plain
                    @click.stop="toggleExpand(item.id)"
                  />
                  <van-button size="mini" plain icon="bars" @click.stop="goEditor(item)" title="工序编排" />
                  <van-button
                    v-if="item.status === 'draft'"
                    icon="edit" size="mini" plain type="primary"
                    @click.stop="openEdit(item)"
                  />
                  <van-button
                    v-if="item.status === 'draft'"
                    icon="success" size="mini" plain type="success"
                    @click.stop="handlePublish(item)"
                  />
                  <van-button
                    v-if="item.status === 'published'"
                    icon="records" size="mini" plain type="warning"
                    @click.stop="handleNewVersion(item)"
                  />
                  <van-button
                    v-if="item.status !== 'archived'"
                    icon="folder" size="mini" plain
                    @click.stop="handleArchive(item)"
                  />
                  <van-button
                    v-if="item.status === 'draft'"
                    icon="delete" size="mini" plain type="danger"
                    @click.stop="handleDelete(item)"
                  />
                </div>
              </td>
            </tr>
            <tr v-if="expandedId === item.id" class="row-detail-row">
              <td :colspan="7">
                <ListRowDetail :item="item" :fields="cfg.rowDetailFields" />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

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
        <van-field v-model="editing.effective_from" label="生效日期" type="date" placeholder="可选" />
        <van-field v-model="editing.effective_to" label="失效日期" type="date" placeholder="可选" />
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

<style scoped>
.route-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.route-table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
  font-size: 14px;
  color: var(--ziwi-text-primary, #1e293b);
  background: var(--ziwi-bg, #fff);
}

.route-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--ziwi-bg-elevated, #f5f7fa);
  text-align: left;
  padding: 10px 12px;
  font-weight: 600;
  white-space: nowrap;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  color: var(--ziwi-text-primary, #1e293b);
}

.route-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  text-align: left;
  vertical-align: middle;
  color: var(--ziwi-text-primary, #1e293b);
}

.route-table tbody td.num {
  text-align: right;
  white-space: nowrap;
}

.route-table tbody td.op {
  text-align: right;
  white-space: normal;
}

.op-btns {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
  max-width: 340px;
}

/* 行展开（并集详情）整行底色弱化，凸显多列并排明细 */
.route-table tbody tr.row-detail-row td {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.02));
  padding: 0;
}

.route-table tbody tr:hover:not(.row-detail-row) {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.04));
}

@media (max-width: 768px) {
  .route-table {
    font-size: 13px;
  }
  .route-table thead th,
  .route-table tbody td {
    padding: 8px 10px;
  }
}
</style>
