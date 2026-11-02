<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showDialog } from 'vant'
import { get, post, put, del, errorText } from '@/api/client'
import ZiwiFormSheet from '@/components/ziwi/ZiwiFormSheet.vue'
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
    showToast(errorText(e, '获取工艺路线列表失败'))
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

const saving = ref(false)

async function handleSave() {
  // 提交中不重复受理（UE-P0-05）：按钮已 loading，这里再兜一道
  if (saving.value) return
  saving.value = true
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
    showToast(errorText(e, '操作失败'))
  } finally {
    saving.value = false
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
        showToast(errorText(e, '发布失败'))
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
        showToast(errorText(e, '归档失败'))
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
    showToast(errorText(e, '创建新版本失败'))
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
        showToast(errorText(e, '删除失败'))
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
  <div class="ziwi-page">
    <!-- 搜索栏 -->
    <div class="ziwi-filter-bar ziwi-gap-3 ziwi-mb-4">
      <div class="ziwi-flex-1 ziwi-min-w-field">
        <van-field
          v-model="keyword"
          placeholder="搜索路线编码/名称"
          clearable
          @keyup.enter="onSearch"
        />
      </div>
      <div class="ziwi-w-36">
        <SelectField v-model="statusFilter" :options="STATUS_OPTIONS" placeholder="状态" clearable />
      </div>
      <div class="ziwi-flex ziwi-flex-wrap ziwi-gap-2">
        <van-button type="primary" size="small" @click="onSearch">搜索</van-button>
        <van-button plain size="small" @click="onReset">重置</van-button>
        <van-button v-perm="'M00:route:create'" type="success" size="small" @click="openCreate">新建路线</van-button>
        <van-button size="small" icon="filter-o" @click="showSearch = true">高级检索</van-button>
      </div>
    </div>

    <!-- 高级检索条件 chips -->
    <div v-if="conditions.length" class="ziwi-flex ziwi-flex-wrap ziwi-gap-2 ziwi-mb-3 ziwi-px-1">
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
    <div v-if="loading" class="ziwi-text-center ziwi-py-10 ziwi-text-muted">加载中...</div>
    <div v-else-if="list.length === 0" class="ziwi-text-center ziwi-py-10 ziwi-text-muted">暂无数据</div>
    <div v-else class="route-table-wrap ziwi-table-scroll">
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
                <!-- 行内操作结构性消掉，同 WorkCenterList。这一页原来最挤：
                     最多 6 个 size="mini" 图标键（展开/编排/编辑/发布/新版本/归档/删除）
                     并排 22×24，油污手套下误触率极高，且"展开"键与整行点击重复。
                     现在行尾只留不可点的展开指示，操作全部移入展开区。 -->
                <van-icon
                  :name="expandedId === item.id ? 'arrow-up' : 'arrow-down'"
                  class="ziwi-row-chevron"
                  aria-hidden="true"
                />
              </td>
            </tr>
            <tr v-if="expandedId === item.id" class="row-detail-row">
              <td :colspan="7">
                <ListRowDetail :item="item" :fields="cfg.rowDetailFields" />
                <div class="ziwi-row-actions">
                  <van-button plain icon="bars" @click.stop="goEditor(item)">工序编排</van-button>
                  <van-button
                    v-if="item.status === 'draft'"
                    v-perm="'M00:route:update'"
                    icon="edit" plain type="primary"
                    @click.stop="openEdit(item)"
                  >编辑</van-button>
                  <van-button
                    v-if="item.status === 'draft'"
                    v-perm="'M00:route:execute'"
                    icon="success" plain type="success"
                    @click.stop="handlePublish(item)"
                  >发布</van-button>
                  <van-button
                    v-if="item.status === 'published'"
                    v-perm="'M00:route_new_version:create'"
                    icon="records" plain type="warning"
                    @click.stop="handleNewVersion(item)"
                  >新版本</van-button>
                  <van-button
                    v-if="item.status !== 'archived'"
                    v-perm="'M00:route_archive:create'"
                    icon="folder" plain
                    @click.stop="handleArchive(item)"
                  >归档</van-button>
                  <van-button
                    v-if="item.status === 'draft'"
                    v-perm="'M00:route:delete'"
                    icon="delete" plain type="danger"
                    @click.stop="handleDelete(item)"
                  >删除</van-button>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- 创建/编辑弹窗 -->
    <ZiwiFormSheet
      v-model:show="showEditDialog"
      :title="isEdit ? '编辑工艺路线' : '新增工艺路线'"
      :submitting="saving"
      submit-text="保存"
      @submit="handleSave"
    >
      <div class="ziwi-stack-3">
        <van-field v-model="editing.code" label="路线编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="路线名称" required placeholder="请输入名称" />
        <van-field label="路线类型" required>
          <template #input>
            <SelectField v-model="editing.route_type" :options="ROUTE_TYPE_OPTIONS" class="ziwi-w-full" />
          </template>
        </van-field>
        <van-field v-model="editing.effective_from" label="生效日期" type="date" placeholder="可选" />
        <van-field v-model="editing.effective_to" label="失效日期" type="date" placeholder="可选" />
        <van-field v-model="editing.description" label="描述" type="textarea" rows="2" placeholder="可选" />
      </div>
    </ZiwiFormSheet>

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

/* .op-btns 已随行内操作移入展开区删除（改用共享类 .ziwi-row-actions）。
   顺带去掉 max-width: 340px —— 那是为了在窄列里硬挤最多 6 个图标键的补丁。 */

/* 行展开（并集详情）整行底色弱化，凸显多列并排明细 */
/* 数据行本身是"点行展开"的点击目标，必须 ≥ --ziwi-touch-min（同 WorkCenterList：
   拿走行内图标键后行高会从 46 掉到 40，原来是 mini 按钮在撑行高）。 */
.route-table tbody tr:not(.row-detail-row) {
  height: var(--ziwi-touch-min);
}

.route-table tbody tr.row-detail-row td {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.02));
  padding: 0;
  /* B-15：同 ProductList —— colspan 单元格要能收缩，明细区才会内部横滚。 */
  max-width: 0;
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
