<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'

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

const list = ref<Product[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const typeFilter = ref('')
const categoryFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<Product>>({})
const isEdit = ref(false)

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
    list.value = res.items || []
  } catch (e: any) {
    showToast(e?.detail?.message || '获取产品列表失败')
  } finally {
    loading.value = false
  }
}

function onSearch() { page.value = 1; fetchData() }
function onReset() { keyword.value = ''; typeFilter.value = ''; categoryFilter.value = ''; onSearch() }

function openCreate() {
  isEdit.value = false
  editing.value = { code: '', name: '', spec: '', unit: '个', product_type: 'final', category: '', weight: null, drawing_url: null, is_active: true, remark: '' }
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
      } catch (e: any) { showToast(e?.detail?.message || '删除失败') }
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
        <van-field v-model="keyword" placeholder="搜索编码/名称/规格" clearable @keyup.enter="onSearch" />
      </div>
      <div class="w-32">
        <SelectField v-model="typeFilter" :options="PRODUCT_TYPE_OPTIONS" placeholder="产品类型" clearable />
      </div>
      <van-field v-model="categoryFilter" placeholder="产品分类" class="w-36" clearable @keyup.enter="onSearch" />
      <div class="flex gap-2">
        <van-button type="primary" size="small" @click="onSearch">搜索</van-button>
        <van-button plain size="small" @click="onReset">重置</van-button>
        <van-button type="success" size="small" @click="openCreate">新增产品</van-button>
      </div>
    </div>

    <!-- 列表 -->
    <div v-if="loading" class="text-center py-10 text-gray-400">加载中...</div>
    <div v-else-if="list.length === 0" class="text-center py-10 text-gray-400">暂无数据</div>
    <van-cell-group v-else>
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          <div class="flex items-center gap-2">
            <span class="font-medium">{{ item.code }}</span>
            <van-tag type="primary" size="small">{{ productTypeLabel(item.product_type) }}</van-tag>
            <van-tag v-if="!item.is_active" type="danger" size="small">禁用</van-tag>
          </div>
          <div class="text-sm text-gray-500 mt-1">{{ item.name }} <span v-if="item.spec">/ {{ item.spec }}</span></div>
        </template>
        <template #label>
          <div class="text-xs text-gray-400 mt-1">
            单位: {{ item.unit }} | 分类: {{ item.category || '-' }}
            <span v-if="item.weight"> | 重量: {{ item.weight }}kg</span>
          </div>
        </template>
        <template #right-icon>
          <div class="flex gap-1">
            <van-button icon="edit" size="small" type="primary" plain @click="openEdit(item)" />
            <van-button icon="delete" size="small" type="danger" plain @click="handleDelete(item)" />
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <!-- 创建/编辑弹窗 -->
    <van-dialog v-model:show="showDialog_" :title="isEdit ? '编辑产品' : '新增产品'" show-cancel-button @confirm="handleSave" class="!w-[500px]">
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
        <van-field v-model="editing.remark" label="备注" type="textarea" rows="2" placeholder="可选" />
      </div>
    </van-dialog>
  </div>
</template>
