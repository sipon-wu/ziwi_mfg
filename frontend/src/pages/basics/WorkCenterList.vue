<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

interface WorkCenter {
  id: number
  code: string
  name: string
  wc_type: string
  org_id: number | null
  efficiency: number
  equipment_count: number
  labor_count: number
  capacity_per_shift: number | null
  is_esd: boolean
  shift_config: string | null
  calendar_override: string | null
  description: string | null
  is_active: boolean
}

const WC_TYPE_OPTIONS = [
  { value: 'production_line', label: '产线' },
  { value: 'work_cell', label: '工作单元' },
  { value: 'workstation', label: '工位' },
]

const rawList = ref<WorkCenter[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const wcTypeFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<WorkCenter>>({})
const isEdit = ref(false)

// 高级检索 + 行展开（并集方式多列并排）
const cfg = getSearchConfig('work-centers')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<WorkCenter>(cfg)
const list = computed<WorkCenter[]>(() =>
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

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: 1, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (wcTypeFilter.value) params.wc_type = wcTypeFilter.value
    const res = await get('/work-centers', { params })
    rawList.value = res.items || []
  } catch (e: any) {
    showToast(e?.detail?.message || '获取工作中心列表失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  fetchData()
}

function onReset() {
  keyword.value = ''
  wcTypeFilter.value = ''
  onSearch()
}

function openCreate() {
  isEdit.value = false
  editing.value = {
    code: '',
    name: '',
    wc_type: 'workstation',
    org_id: null,
    efficiency: 0.85,
    equipment_count: 0,
    labor_count: 0,
    capacity_per_shift: null,
    is_esd: false,
    shift_config: null,
    calendar_override: null,
    description: null,
    is_active: true,
  }
  showDialog_.value = true
}

function openEdit(item: WorkCenter) {
  isEdit.value = true
  editing.value = { ...item }
  showDialog_.value = true
}

async function handleSave() {
  try {
    const data = { ...editing.value }
    if (isEdit.value) {
      await put(`/work-centers/${data.id}`, data)
      showToast('工作中心更新成功')
    } else {
      await post('/work-centers', data)
      showToast('工作中心创建成功')
    }
    showDialog_.value = false
    page.value = 1
    fetchData()
  } catch (e: any) {
    showToast(e?.detail?.message || '操作失败')
  }
}

async function handleDelete(item: WorkCenter) {
  showDialog({
    title: '确认删除',
    message: `确定删除工作中心「${item.code} - ${item.name}」？`,
    showCancelButton: true,
  }).then(async (action: string) => {
    if (action === 'confirm') {
      try {
        await del(`/work-centers/${item.id}`)
        showToast('删除成功')
        page.value = 1
        fetchData()
      } catch (e: any) {
        showToast(e?.detail?.message || '删除失败')
      }
    }
  })
}

function getWcTypeLabel(v: string): string {
  return WC_TYPE_OPTIONS.find(o => o.value === v)?.label || v
}

onMounted(() => {
  fetchData()
})
</script>

<template>
  <div class="p-4">
    <!-- 搜索栏 -->
    <div class="flex flex-wrap gap-3 mb-4 items-end">
      <div class="flex-1 min-w-[200px]">
        <van-field
          v-model="keyword"
          placeholder="搜索工作中心编码/名称"
          clearable
          @keyup.enter="onSearch"
        />
      </div>
      <div class="w-40">
        <SelectField v-model="wcTypeFilter" :options="WC_TYPE_OPTIONS" placeholder="工作中心类型" clearable />
      </div>
      <div class="flex gap-2">
        <van-button type="primary" size="small" @click="onSearch">搜索</van-button>
        <van-button plain size="small" @click="onReset">重置</van-button>
        <van-button type="success" size="small" @click="openCreate">新增工作中心</van-button>
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
    <div v-else class="wc-table-wrap">
      <table class="wc-table">
        <thead>
          <tr>
            <th>工作中心编码</th>
            <th>工作中心名称</th>
            <th>类型</th>
            <th class="num">效率</th>
            <th class="num">设备数</th>
            <th class="num">人员数</th>
            <th>ESD</th>
            <th>状态</th>
            <th class="op">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="item in list" :key="item.id">
            <tr @click="toggleExpand(item.id)">
              <td>{{ item.code }}</td>
              <td>{{ item.name }}</td>
              <td>
                <van-tag type="primary" size="small">{{ getWcTypeLabel(item.wc_type) }}</van-tag>
              </td>
              <td class="num">{{ (item.efficiency * 100).toFixed(0) }}%</td>
              <td class="num">{{ item.equipment_count }}</td>
              <td class="num">{{ item.labor_count }}</td>
              <td>
                <van-tag v-if="item.is_esd" type="warning" size="small">是</van-tag>
                <span v-else class="text-gray-400">—</span>
              </td>
              <td>
                <van-tag v-if="item.is_active" type="success" size="small">启用</van-tag>
                <van-tag v-else type="default" size="small">禁用</van-tag>
              </td>
              <td class="op">
                <div class="op-btns">
                  <van-button
                    :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'"
                    size="mini"
                    plain
                    @click.stop="toggleExpand(item.id)"
                  />
                  <van-button icon="edit" size="mini" plain type="primary" @click.stop="openEdit(item)" />
                  <van-button icon="delete" size="mini" plain type="danger" @click.stop="handleDelete(item)" />
                </div>
              </td>
            </tr>
            <tr v-if="expandedId === item.id" class="row-detail-row">
              <td :colspan="9">
                <ListRowDetail :item="item" :fields="cfg.rowDetailFields" />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- 创建/编辑弹窗 -->
    <van-dialog
      v-model:show="showDialog_"
      :title="isEdit ? '编辑工作中心' : '新增工作中心'"
      show-cancel-button
      @confirm="handleSave"
      class="!w-[500px]"
    >
      <div class="p-4 space-y-3 max-h-[70vh] overflow-y-auto">
        <van-field v-model="editing.code" label="工作中心编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="工作中心名称" required placeholder="请输入名称" />
        <van-field label="工作中心类型" required>
          <template #input>
            <SelectField v-model="editing.wc_type" :options="WC_TYPE_OPTIONS" class="w-full" />
          </template>
        </van-field>
        <van-field v-model.number="editing.efficiency" label="效率因子" type="number" placeholder="0.85" />
        <van-field v-model.number="editing.equipment_count" label="设备数" type="number" placeholder="0" />
        <van-field v-model.number="editing.labor_count" label="人员数" type="number" placeholder="0" />
        <van-field v-model.number="editing.capacity_per_shift" label="每班产能(件)" type="number" placeholder="可选" />
        <van-field label="ESD静电防护">
          <template #input>
            <van-switch v-model="editing.is_esd" />
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

<style scoped>
.wc-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.wc-table {
  width: 100%;
  min-width: 920px;
  border-collapse: collapse;
  font-size: 14px;
  color: var(--ziwi-text-primary, #1e293b);
  background: var(--ziwi-bg, #fff);
}

.wc-table thead th {
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

.wc-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  text-align: left;
  vertical-align: middle;
  color: var(--ziwi-text-primary, #1e293b);
}

.wc-table tbody td.num {
  text-align: right;
  white-space: nowrap;
}

.wc-table tbody td.op {
  text-align: right;
  white-space: nowrap;
}

.op-btns {
  display: inline-flex;
  gap: 6px;
  justify-content: flex-end;
}

/* 行展开（并集详情）整行底色弱化，凸显多列并排明细 */
.wc-table tbody tr.row-detail-row td {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.02));
  padding: 0;
}

.wc-table tbody tr:hover:not(.row-detail-row) {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.04));
}

@media (max-width: 768px) {
  .wc-table {
    font-size: 13px;
  }
  .wc-table thead th,
  .wc-table tbody td {
    padding: 8px 10px;
  }
}
</style>
