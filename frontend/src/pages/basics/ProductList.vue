<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

interface Product {
  id: number
  code: string
  name: string
  spec: string | null
  unit: string
  product_type: string
  category: string | null
  weight: number | null
  drawing_url: string | null
  is_active: boolean
  remark: string | null
  created_at: string
}

const PRODUCT_TYPE_OPTIONS = [
  { value: 'final', label: '成品' },
  { value: 'semi', label: '半成品' },
  { value: 'raw', label: '原材料' },
]

const rawList = ref<Product[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const typeFilter = ref('')
const categoryFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<Product>>({})
const isEdit = ref(false)

// 高级检索 + 行展开（并集方式多列并排）
const cfg = getSearchConfig('products')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<Product>(cfg)
const list = computed<Product[]>(() =>
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

function productTypeLabel(v: string): string {
  return PRODUCT_TYPE_OPTIONS.find(o => o.value === v)?.label || v
}

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: 1, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (typeFilter.value) params.product_type = typeFilter.value
    if (categoryFilter.value) params.category = categoryFilter.value
    const res = await get('/products', { params })
    rawList.value = res.items || []
  } catch (e: any) {
    showToast(e?.detail?.message || '获取产品列表失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  fetchData()
}
function onReset() {
  keyword.value = ''
  typeFilter.value = ''
  categoryFilter.value = ''
  onSearch()
}

function openCreate() {
  isEdit.value = false
  editing.value = {
    code: '',
    name: '',
    spec: '',
    unit: '个',
    product_type: 'final',
    category: '',
    weight: null,
    drawing_url: null,
    is_active: true,
    remark: '',
  }
  showDialog_.value = true
}

function openEdit(item: Product) {
  isEdit.value = true
  editing.value = { ...item }
  showDialog_.value = true
}

async function handleSave() {
  try {
    const data = { ...editing.value }
    if (isEdit.value) {
      await put(`/products/${data.id}`, data)
      showToast('更新成功')
    } else {
      await post('/products', data)
      showToast('创建成功')
    }
    showDialog_.value = false
    page.value = 1
    fetchData()
  } catch (e: any) {
    showToast(e?.detail?.message || '操作失败')
  }
}

async function handleDelete(item: Product) {
  showDialog({
    title: '确认删除',
    message: `确定删除产品「${item.code} - ${item.name}」？`,
    showCancelButton: true,
  }).then(async (action: string) => {
    if (action === 'confirm') {
      try {
        await del(`/products/${item.id}`)
        showToast('删除成功')
        page.value = 1
        fetchData()
      } catch (e: any) {
        showToast(e?.detail?.message || '删除失败')
      }
    }
  })
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
          placeholder="搜索编码/名称/规格"
          clearable
          @keyup.enter="onSearch"
        />
      </div>
      <div class="w-32">
        <SelectField v-model="typeFilter" :options="PRODUCT_TYPE_OPTIONS" placeholder="产品类型" clearable />
      </div>
      <van-field v-model="categoryFilter" placeholder="产品分类" class="w-36" clearable @keyup.enter="onSearch" />
      <div class="flex gap-2">
        <van-button type="primary" size="small" @click="onSearch">搜索</van-button>
        <van-button plain size="small" @click="onReset">重置</van-button>
        <van-button type="success" size="small" @click="openCreate">新增产品</van-button>
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
    <div v-else class="prod-table-wrap">
      <table class="prod-table">
        <thead>
          <tr>
            <th>产品编码</th>
            <th>产品名称</th>
            <th>规格型号</th>
            <th>单位</th>
            <th>产品类型</th>
            <th>产品分类</th>
            <th>状态</th>
            <th class="op">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="item in list" :key="item.id">
            <tr @click="toggleExpand(item.id)">
              <td>{{ item.code }}</td>
              <td>{{ item.name }}</td>
              <td>{{ item.spec || '-' }}</td>
              <td>{{ item.unit }}</td>
              <td>{{ productTypeLabel(item.product_type) }}</td>
              <td>{{ item.category || '-' }}</td>
              <td>
                <van-tag :type="item.is_active ? 'success' : 'danger'" size="small">
                  {{ item.is_active ? '启用' : '禁用' }}
                </van-tag>
              </td>
              <td class="op">
                <div class="op-btns">
                  <van-button
                    :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'"
                    size="mini"
                    plain
                    @click.stop="toggleExpand(item.id)"
                  />
                  <van-button
                    icon="edit" size="mini" plain type="primary"
                    @click.stop="openEdit(item)"
                  />
                  <van-button
                    icon="delete" size="mini" plain type="danger"
                    @click.stop="handleDelete(item)"
                  />
                </div>
              </td>
            </tr>
            <tr v-if="expandedId === item.id" class="row-detail-row">
              <td :colspan="8">
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
      :title="isEdit ? '编辑产品' : '新增产品'"
      show-cancel-button
      @confirm="handleSave"
      class="!w-[500px]"
    >
      <div class="p-4 space-y-3 max-h-[70vh] overflow-y-auto">
        <van-field v-model="editing.code" label="产品编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="产品名称" required placeholder="请输入名称" />
        <van-field v-model="editing.spec" label="规格型号" placeholder="可选" />
        <van-field label="产品类型" required>
          <template #input>
            <SelectField v-model="editing.product_type" :options="PRODUCT_TYPE_OPTIONS" class="w-full" />
          </template>
        </van-field>
        <van-field v-model="editing.unit" label="单位" required placeholder="个/件/套/Kg/m" />
        <van-field v-model="editing.category" label="产品分类" placeholder="可选" />
        <van-field v-model.number="editing.weight" label="重量(kg)" type="number" placeholder="可选" />
        <van-field label="启用状态">
          <template #input>
            <van-switch v-model="editing.is_active" />
          </template>
        </van-field>
        <van-field v-model="editing.remark" label="备注" type="textarea" rows="2" placeholder="可选" />
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
.prod-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.prod-table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  font-size: 14px;
  color: var(--ziwi-text-primary, #1e293b);
  background: var(--ziwi-bg, #fff);
}

.prod-table thead th {
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

.prod-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  text-align: left;
  vertical-align: middle;
  color: var(--ziwi-text-primary, #1e293b);
}

.prod-table tbody td.op {
  text-align: right;
  white-space: normal;
}

.op-btns {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
  max-width: 220px;
}

/* 行展开（并集详情）整行底色弱化，凸显多列并排明细 */
.prod-table tbody tr.row-detail-row td {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.02));
  padding: 0;
}

.prod-table tbody tr:hover:not(.row-detail-row) {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.04));
}

@media (max-width: 768px) {
  .prod-table {
    font-size: 13px;
  }
  .prod-table thead th,
  .prod-table tbody td {
    padding: 8px 10px;
  }
}
</style>
