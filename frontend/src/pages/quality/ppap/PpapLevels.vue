<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

interface PpapLevel {
  id: number
  level_no: number
  level_name: string
  is_default: boolean
  is_custom: boolean
  remark: string | null
  created_at: string
  updated_at: string
}

const list = ref<PpapLevel[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const showDialog_ = ref(false)
const editingItem = ref<PpapLevel | null>(null)
const form = ref({
  level_no: 1,
  level_name: '',
  is_default: false,
  is_custom: false,
  remark: '',
})
const submitting = ref(false)

async function loadData() {
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<PpapLevel>>('/ppap/levels', { ...p })
  })
  list.value = (items as unknown) as PpapLevel[]
}

function openCreate() {
  editingItem.value = null
  form.value = { level_no: 1, level_name: '', is_default: false, is_custom: false, remark: '' }
  showDialog_.value = true
}

function openEdit(item: PpapLevel) {
  editingItem.value = item
  form.value = {
    level_no: item.level_no,
    level_name: item.level_name,
    is_default: item.is_default,
    is_custom: item.is_custom,
    remark: item.remark || '',
  }
  showDialog_.value = true
}

async function handleSave() {
  if (!form.value.level_name) {
    showToast('请输入等级名称')
    return
  }
  submitting.value = true
  try {
    if (editingItem.value) {
      await put(`/ppap/levels/${editingItem.value.id}`, form.value)
      showToast('更新成功')
    } else {
      await post('/ppap/levels', form.value)
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

async function handleDelete(item: PpapLevel) {
  try {
    await showConfirmDialog({ message: `确定删除等级「${item.level_name}」？` })
    await del(`/ppap/levels/${item.id}`)
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
    <van-nav-bar title="PPAP等级配置" right-text="新增等级" @click-right="openCreate" />

    <van-list v-model:loading="loading" :finished="!total || list.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          {{ item.level_name }}
          <van-tag v-if="item.is_default" type="success" style="margin-left:6px">默认</van-tag>
          <van-tag v-if="item.is_custom" type="warning" style="margin-left:4px">自定义</van-tag>
        </template>
        <template #label>
          <div>等级: {{ item.level_no }}级</div>
          <div v-if="item.remark">说明: {{ item.remark }}</div>
        </template>
        <template #value>
          <div style="display:flex; gap:4px">
            <van-button size="mini" plain type="primary" @click="openEdit(item)">编辑</van-button>
            <van-button size="mini" plain type="danger" @click="handleDelete(item)">删除</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && list.length === 0" description="暂无等级配置" />

    <van-dialog v-model:show="showDialog_" :title="editingItem ? '编辑等级' : '新增等级'" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleSave(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model.number="form.level_no" label="等级编号" type="digit" placeholder="1-5" :rules="[{ required: true }]" />
        <van-field v-model="form.level_name" label="等级名称" placeholder="如：Level 1" :rules="[{ required: true }]" />
        <van-field name="is_default" label="设为默认">
          <template #input>
            <van-switch v-model="form.is_default" />
          </template>
        </van-field>
        <van-field name="is_custom" label="自定义等级">
          <template #input>
            <van-switch v-model="form.is_custom" />
          </template>
        </van-field>
        <van-field v-model="form.remark" label="备注" type="textarea" rows="2" placeholder="选填" />
      </div>
    </van-dialog>
  </div>
</template>
