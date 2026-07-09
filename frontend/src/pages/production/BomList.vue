<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

interface BomItem {
  id: number
  product_id: number
  product_name?: string
  material_code: string
  material_name: string
  qty_per_unit: number
  unit: string
  material_type: string
  version: number
  effective_from: string
  is_active: boolean
  remark: string
  created_at: string
  updated_at: string
}

const list = ref<BomItem[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const productFilter = ref('')
const showDialog_ = ref(false)
const editingItem = ref<BomItem | null>(null)
const form = ref({
  product_id: 0,
  material_code: '',
  material_name: '',
  qty_per_unit: 1,
  unit: '个',
  material_type: 'raw',
  version: 1,
  effective_from: '',
  is_active: true,
  remark: '',
})
const submitting = ref(false)

const materialTypeOptions = [
  { value: 'raw', label: '原材料' },
  { value: 'semi', label: '半成品' },
  { value: 'package', label: '包装材料' },
  { value: 'consumable', label: '消耗品' },
]

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (productFilter.value) params.product_id = productFilter.value

  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<BomItem>>('/boms', { ...params, ...p })
  })
  list.value = (items as unknown) as BomItem[]
}

function onSearch(val: string) {
  productFilter.value = val
  resetPage()
  loadData()
}

function openCreate() {
  editingItem.value = null
  form.value = {
    product_id: 0,
    material_code: '',
    material_name: '',
    qty_per_unit: 1,
    unit: '个',
    material_type: 'raw',
    version: 1,
    effective_from: '',
    is_active: true,
    remark: '',
  }
  showDialog_.value = true
}

function openEdit(item: BomItem) {
  editingItem.value = item
  form.value = {
    product_id: item.product_id,
    material_code: item.material_code,
    material_name: item.material_name,
    qty_per_unit: item.qty_per_unit,
    unit: item.unit,
    material_type: item.material_type,
    version: item.version,
    effective_from: item.effective_from || '',
    is_active: item.is_active,
    remark: item.remark || '',
  }
  showDialog_.value = true
}

async function handleSave() {
  if (!form.value.material_code || !form.value.material_name) {
    showToast('请填写物料编码和物料名称')
    return
  }
  submitting.value = true
  try {
    if (editingItem.value) {
      await put(`/boms/${editingItem.value.id}`, form.value)
      showToast('更新成功')
    } else {
      await post('/boms', form.value)
      showToast('创建成功')
    }
    showDialog_.value = false
    loadData()
  } catch {
    showToast(editingItem.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(item: BomItem) {
  try {
    await showConfirmDialog({ message: `确定删除物料 ${item.material_name}？` })
    await del(`/boms/${item.id}`)
    showToast('删除成功')
    loadData()
  } catch {
    // cancelled or error
  }
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="BOM管理" right-text="新增物料" @click-right="openCreate" />

    <van-search v-model="productFilter" placeholder="搜索产品ID" @search="onSearch" />

    <van-list v-model:loading="loading" :finished="!total || list.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          <span>{{ item.material_name }}</span>
          <van-tag v-if="item.is_active" type="success" style="margin-left:8px">当前版本</van-tag>
        </template>
        <template #label>
          <div>物料编码: {{ item.material_code }}</div>
          <div>用量: {{ item.qty_per_unit }} {{ item.unit }} | 版本: V{{ item.version }}</div>
          <div v-if="item.effective_from">生效: {{ item.effective_from }}</div>
        </template>
        <template #value>
          <div style="display:flex; gap:4px">
            <van-button size="mini" plain type="primary" @click="openEdit(item)">编辑</van-button>
            <van-button size="mini" plain type="danger" @click="handleDelete(item)">删除</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && list.length === 0" description="暂无BOM记录" />

    <!-- 创建/编辑弹窗 -->
    <van-dialog v-model:show="showDialog_" :title="editingItem ? '编辑物料' : '新增物料'" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleSave(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model.number="form.product_id" label="产品ID" type="digit" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="form.material_code" label="物料编码" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="form.material_name" label="物料名称" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model.number="form.qty_per_unit" label="用量" type="digit" placeholder="必填" />
        <van-field v-model="form.unit" label="单位" placeholder="个" />
        <van-field name="material_type" label="物料类型">
          <template #input>
            <van-radio-group v-model="form.material_type" direction="horizontal">
              <van-radio v-for="t in materialTypeOptions" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field v-model.number="form.version" label="版本号" type="digit" />
        <van-field v-model="form.effective_from" label="生效日期" type="date" />
        <van-field name="is_active" label="是否激活">
          <template #input>
            <van-switch v-model="form.is_active" />
          </template>
        </van-field>
        <van-field v-model="form.remark" label="备注" type="textarea" rows="2" />
      </div>
    </van-dialog>
  </div>
</template>
