<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import { listStandards, createStandard, updateStandard, deleteStandard } from '@/api/lab'
import type { TestStandard } from '@/api/lab'

const router = useRouter()
const standards = ref<TestStandard[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

// 表单
const showForm = ref(false)
const showCategoryPicker = ref(false)
const editingId = ref<number | null>(null)
const form = ref({
  name: '',
  category: '',
  method: '',
  default_lower_limit: null as number | null,
  default_upper_limit: null as number | null,
  unit: '',
  description: '',
})

const categoryOptions = [
  { value: 'mechanical', label: '力学性能' },
  { value: 'metallographic', label: '金相分析' },
  { value: 'chemical', label: '化学成分' },
  { value: 'dimensional', label: '尺寸测量' },
  { value: 'environmental', label: '环境试验' },
  { value: 'physical', label: '物理性能' },
  { value: 'aging', label: '老化试验' },
  { value: 'ndt', label: '无损检测' },
  { value: 'cleanliness', label: '洁净度' },
  { value: 'other', label: '其他' },
]

async function fetch() {
  loading.value = true
  try {
    const res = await listStandards({ page: page.value, page_size: 20 })
    standards.value = res.items || []
    total.value = res.total || 0
  } finally { loading.value = false }
}

onMounted(fetch)

function openCreate() {
  editingId.value = null
  form.value = { name: '', category: '', method: '', default_lower_limit: null, default_upper_limit: null, unit: '', description: '' }
  showForm.value = true
}

function openEdit(item: TestStandard) {
  editingId.value = item.id
  form.value = {
    name: item.name,
    category: item.category || '',
    method: item.method || '',
    default_lower_limit: item.default_lower_limit,
    default_upper_limit: item.default_upper_limit,
    unit: item.unit || '',
    description: item.description || '',
  }
  showForm.value = true
}

async function handleSave() {
  if (!form.value.name) { showToast('请输入标准名称'); return }
  try {
    if (editingId.value) {
      const data: any = {}
      Object.entries(form.value).forEach(([k, v]) => { if (v !== null && v !== '') data[k] = v })
      await updateStandard(editingId.value, data)
      showToast('更新成功')
    } else {
      await createStandard({ ...form.value, default_lower_limit: form.value.default_lower_limit || undefined, default_upper_limit: form.value.default_upper_limit || undefined })
      showToast('创建成功')
    }
    showForm.value = false
    fetch()
  } catch (e: any) {
    showToast(e.response?.data?.detail?.message || '操作失败')
  }
}

async function handleDelete(item: TestStandard) {
  try {
    await showConfirmDialog({ title: '删除标准', message: `确认删除「${item.name}」？` })
    await deleteStandard(item.id)
    showToast('删除成功')
    fetch()
  } catch { /* cancelled */ }
}
</script>

<template>
  <div>
    <van-nav-bar title="检验标准库" left-text="返回" @click-left="router.back()">
      <template #right>
        <van-button size="small" type="primary" @click="openCreate">新建</van-button>
      </template>
    </van-nav-bar>

    <van-list v-model:loading="loading" :finished="standards.length >= total" @load="fetch">
      <van-cell v-for="item in standards" :key="item.id">
        <template #title>
          <span style="font-weight: bold">{{ item.name }}</span>
          <van-tag v-if="item.category" style="margin-left: 6px" type="primary">{{ item.category }}</van-tag>
        </template>
        <template #label>
          <div>方法: {{ item.method || '-' }}</div>
          <div v-if="item.default_lower_limit !== null || item.default_upper_limit !== null">
            默认限值: {{ item.default_lower_limit ?? '-' }} ~ {{ item.default_upper_limit ?? '-' }} {{ item.unit || '' }}
          </div>
          <div v-if="item.description" style="font-size: 12px; color: #999">{{ item.description }}</div>
        </template>
        <template #value>
          <van-space>
            <van-button size="mini" type="primary" plain @click="openEdit(item)">编辑</van-button>
            <van-button size="mini" type="danger" plain @click="handleDelete(item)">删除</van-button>
          </van-space>
        </template>
      </van-cell>
    </van-list>

    <!-- 创建/编辑弹窗 -->
    <van-dialog
      v-model:show="showForm"
      :title="editingId ? '编辑标准' : '新建标准'"
      show-cancel-button
      @confirm="handleSave"
      style="max-height: 80vh; overflow: auto"
    >
      <van-form @submit.prevent="handleSave">
        <van-cell-group inset>
          <van-field v-model="form.name" label="标准名称" placeholder="请输入" :rules="[{ required: true, message: '请输入名称' }]" />
          <van-field v-model="form.category" label="分类" placeholder="请选择" is-link readonly @click="showCategoryPicker = true" />
          <van-field v-model="form.method" label="检测方法" placeholder="请输入" />
          <van-field v-model.number="form.default_lower_limit" label="默认下限" type="number" placeholder="下限值" />
          <van-field v-model.number="form.default_upper_limit" label="默认上限" type="number" placeholder="上限值" />
          <van-field v-model="form.unit" label="单位" placeholder="如 MPa, mm" />
          <van-field v-model="form.description" label="描述" type="textarea" rows="2" placeholder="标准描述" />
        </van-cell-group>
      </van-form>
    </van-dialog>

    <van-action-sheet v-model:show="showCategoryPicker" :actions="categoryOptions" @select="(a: any) => { form.category = a.value; showCategoryPicker = false }" />
  </div>
</template>

<script lang="ts">
export default { name: 'LabStandardsList' }
</script>
