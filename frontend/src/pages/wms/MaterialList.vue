<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'

interface Material { id: number; code: string; name: string; spec: string; unit: string; material_type: string; material_category: string; is_batch_managed: boolean; is_active: boolean }

const list = ref<Material[]>([])
const loading = ref(false)
const keyword = ref('')
const materialType = ref('')
const page = ref(1)
const total = ref(0)
const pageSize = 20
const showForm = ref(false)
const editing = ref<Material | null>(null)
const form = ref({ code: '', name: '', spec: '', unit: '个', material_type: 'raw', material_category: '', is_batch_managed: false, is_active: true, min_stock_qty: 0, max_stock_qty: 0, safety_stock_qty: 0 })
const submitting = ref(false)

const typeOpts = [{ value: 'raw', label: '原材料' }, { value: 'semi', label: '半成品' }, { value: 'finished', label: '成品' }, { value: 'consumable', label: '消耗品' }, { value: 'package', label: '包装' }]

async function loadData() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<Material>>('/wms/materials', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, material_type: materialType.value || undefined })
    list.value = res.items as Material[]
    total.value = res.total
  } finally { loading.value = false }
}

function onSearch() { page.value = 1; loadData() }
function openCreate() { editing.value = null; form.value = { code: '', name: '', spec: '', unit: '个', material_type: 'raw', material_category: '', is_batch_managed: false, is_active: true, min_stock_qty: 0, max_stock_qty: 0, safety_stock_qty: 0 }; showForm.value = true }
function openEdit(item: Material) {
  editing.value = item
  form.value = { code: item.code, name: item.name, spec: item.spec || '', unit: item.unit, material_type: item.material_type, material_category: item.material_category || '', is_batch_managed: item.is_batch_managed, is_active: item.is_active, min_stock_qty: 0, max_stock_qty: 0, safety_stock_qty: 0 }
  showForm.value = true
}
async function handleSave() {
  if (!form.value.code || !form.value.name) { showToast('请填写编码和名称'); return }
  submitting.value = true
  try {
    if (editing.value) { await put(`/wms/materials/${editing.value.id}`, form.value); showToast('更新成功') }
    else { await post('/wms/materials', form.value); showToast('创建成功') }
    showForm.value = false; loadData()
  } catch { showToast(editing.value ? '更新失败' : '创建失败') }
  finally { submitting.value = false }
}
async function handleDelete(item: Material) {
  try { await showConfirmDialog({ message: `确定删除 ${item.name}？` }); await del(`/wms/materials/${item.id}`); showToast('删除成功'); loadData() }
  catch { /* cancelled */ }
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="物料主数据" right-text="新增物料" @click-right="openCreate" />
    <van-search v-model="keyword" placeholder="搜索编码/名称/规格" @search="onSearch" />
    <van-cell-group inset style="margin:8px">
      <van-radio-group v-model="materialType" direction="horizontal" @change="onSearch">
        <van-radio name="" style="margin-right:8px">全部</van-radio>
        <van-radio v-for="t in typeOpts" :key="t.value" :name="t.value" style="margin-right:8px">{{ t.label }}</van-radio>
      </van-radio-group>
    </van-cell-group>

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          <span>{{ item.name }}</span>
          <van-tag v-if="item.is_batch_managed" type="warning" style="margin-left:6px">批次</van-tag>
        </template>
        <template #label>
          <div>编码: {{ item.code }} | 规格: {{ item.spec || '-' }} | 单位: {{ item.unit }}</div>
          <div>类型: {{ typeOpts.find(t => t.value === item.material_type)?.label || item.material_type }} | 分类: {{ item.material_category || '-' }}</div>
        </template>
        <template #value>
          <van-button size="mini" plain type="primary" @click="openEdit(item)">编辑</van-button>
          <van-button size="mini" plain type="danger" style="margin-left:4px" @click="handleDelete(item)">删除</van-button>
        </template>
      </van-cell>
    </van-list>
    <van-empty v-if="!loading && list.length === 0" description="暂无物料" />

    <van-dialog v-model:show="showForm" :title="editing ? '编辑物料' : '新增物料'" show-cancel-button
      :before-close="async (a: string) => { if (a === 'confirm') { await handleSave(); return false } return true }">
      <div style="padding:16px">
        <van-field v-model="form.code" label="物料编码" placeholder="必填" />
        <van-field v-model="form.name" label="物料名称" placeholder="必填" />
        <van-field v-model="form.spec" label="规格型号" />
        <van-field v-model="form.unit" label="计量单位" />
        <van-field name="material_type" label="物料类型">
          <template #input><van-radio-group v-model="form.material_type" direction="horizontal">
            <van-radio v-for="t in typeOpts" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
          </van-radio-group></template>
        </van-field>
        <van-field v-model="form.material_category" label="物料分类" />
        <van-field name="is_batch_managed" label="批次管理"><template #input><van-switch v-model="form.is_batch_managed" /></template></van-field>
        <van-field name="is_active" label="启用"><template #input><van-switch v-model="form.is_active" /></template></van-field>
      </div>
    </van-dialog>
  </div>
</template>
