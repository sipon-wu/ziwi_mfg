<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

interface PpapElement {
  id: number
  element_code: string
  element_name: string
  description: string | null
  is_required: boolean
  sort_order: number
  customer_id: number | null
  level_no: number
  has_template: boolean
  template_file_url: string | null
}

const list = ref<PpapElement[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const levelFilter = ref('')
const showDialog_ = ref(false)
const editingItem = ref<PpapElement | null>(null)
const form = ref({
  element_code: '',
  element_name: '',
  description: '',
  is_required: true,
  sort_order: 0,
  customer_id: null as number | null,
  level_no: 1,
  has_template: false,
  template_file_url: '',
})
const submitting = ref(false)
const customerIdStr = ref('')

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (levelFilter.value) params.level_no = levelFilter.value

  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<PpapElement>>('/ppap/elements', { ...params, ...p })
  })
  list.value = (items as unknown) as PpapElement[]
}

function onLevelChange() {
  resetPage()
  loadData()
}

function openCreate() {
  editingItem.value = null
  form.value = {
    element_code: '',
    element_name: '',
    description: '',
    is_required: true,
    sort_order: 0,
    customer_id: null,
    level_no: 1,
    has_template: false,
    template_file_url: '',
  }
  customerIdStr.value = ''
  showDialog_.value = true
}

function openEdit(item: PpapElement) {
  editingItem.value = item
  form.value = {
    element_code: item.element_code,
    element_name: item.element_name,
    description: item.description || '',
    is_required: item.is_required,
    sort_order: item.sort_order,
    customer_id: item.customer_id,
    level_no: item.level_no,
    has_template: item.has_template,
    template_file_url: item.template_file_url || '',
  }
  customerIdStr.value = item.customer_id?.toString() || ''
  showDialog_.value = true
}

async function handleSave() {
  if (!form.value.element_code || !form.value.element_name) {
    showToast('请填写要素编码和名称')
    return
  }
  form.value.customer_id = customerIdStr.value ? Number(customerIdStr.value) : null
  submitting.value = true
  try {
    if (editingItem.value) {
      await put(`/ppap/elements/${editingItem.value.id}`, form.value)
      showToast('更新成功')
    } else {
      await post('/ppap/elements', form.value)
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

async function handleDelete(item: PpapElement) {
  try {
    await showConfirmDialog({ message: `确定删除要素「${item.element_name}」？` })
    await del(`/ppap/elements/${item.id}`)
    showToast('删除成功')
    loadData()
  } catch {
    // cancelled
  }
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="PPAP要素模板" right-text="新增要素" @click-right="openCreate" />

    <div style="display:flex; gap:8px; margin:12px; flex-wrap:wrap;">
      <van-tag
        v-for="lv in [1,2,3,4,5]" :key="lv"
        :type="levelFilter === lv.toString() ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="levelFilter = levelFilter === lv.toString() ? '' : lv.toString(); onLevelChange()"
      >{{ lv }}级</van-tag>
    </div>

    <van-list v-model:loading="loading" :finished="!total || list.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          {{ item.element_name }}
          <van-tag v-if="item.is_required" type="danger" style="margin-left:4px">必填</van-tag>
          <van-tag v-else type="default" style="margin-left:4px">选填</van-tag>
          <van-tag v-if="item.has_template" type="success" style="margin-left:4px">有模板</van-tag>
        </template>
        <template #label>
          <div>编码: {{ item.element_code }} | 等级: {{ item.level_no }}级 | 排序: {{ item.sort_order }}</div>
          <div v-if="item.description">{{ item.description }}</div>
        </template>
        <template #value>
          <div style="display:flex; gap:4px">
            <van-button size="mini" plain type="primary" @click="openEdit(item)">编辑</van-button>
            <van-button size="mini" plain type="danger" @click="handleDelete(item)">删除</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && list.length === 0" description="暂无要素模板" />

    <van-dialog v-model:show="showDialog_" :title="editingItem ? '编辑要素' : '新增要素'" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleSave(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model="form.element_code" label="要素编码" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="form.element_name" label="要素名称" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="form.description" label="描述" type="textarea" rows="2" placeholder="选填" />
        <van-field name="is_required" label="是否必填">
          <template #input>
            <van-switch v-model="form.is_required" />
          </template>
        </van-field>
        <van-field v-model.number="form.sort_order" label="排序号" type="digit" />
        <van-field v-model.number="form.level_no" label="适用等级" type="digit" placeholder="1" />
        <van-field v-model="customerIdStr" label="客户ID" type="digit" placeholder="选填" />
        <van-field name="has_template" label="有模板文件">
          <template #input>
            <van-switch v-model="form.has_template" />
          </template>
        </van-field>
        <van-field v-if="form.has_template" v-model="form.template_file_url" label="模板URL" placeholder="选填" />
      </div>
    </van-dialog>
  </div>
</template>
