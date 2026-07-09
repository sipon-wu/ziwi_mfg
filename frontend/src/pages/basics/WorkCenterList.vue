<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'

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

const list = ref<WorkCenter[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const finished = ref(false)
const keyword = ref('')
const wcTypeFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<WorkCenter>>({})
const isEdit = ref(false)

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: page.value, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (wcTypeFilter.value) params.wc_type = wcTypeFilter.value
    const res = await get('/api/v1/work-centers', { params })
    if (page.value === 1) {
      list.value = res.data.items
    } else {
      list.value.push(...res.data.items)
    }
    total.value = res.data.total
    finished.value = list.value.length >= total.value
  } catch (e: any) {
    showToast(e?.detail?.message || '获取工作中心列表失败')
  } finally {
    loading.value = false
  }
}

function onLoad() {
  fetchData()
}

function onSearch() {
  page.value = 1
  finished.value = false
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
      await put(`/api/v1/work-centers/${data.id}`, data)
      showToast('工作中心更新成功')
    } else {
      await post('/api/v1/work-centers', data)
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
        await del(`/api/v1/work-centers/${item.id}`)
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
        <van-select
          v-model="wcTypeFilter"
          placeholder="工作中心类型"
          clearable
        >
          <van-option
            v-for="opt in WC_TYPE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            :label="opt.label"
          />
        </van-select>
      </div>
      <div class="flex gap-2">
        <van-button type="primary" size="small" @click="onSearch">搜索</van-button>
        <van-button plain size="small" @click="onReset">重置</van-button>
        <van-button type="success" size="small" @click="openCreate">新增工作中心</van-button>
      </div>
    </div>

    <!-- 列表 -->
    <van-list v-model:loading="loading" :finished="finished" finished-text="没有更多了" @load="onLoad">
      <van-cell-group>
        <van-cell
          v-for="item in list"
          :key="item.id"
        >
          <template #title>
            <div class="flex items-center gap-2">
              <span class="font-medium">{{ item.code }}</span>
              <van-tag type="primary" size="small">{{ getWcTypeLabel(item.wc_type) }}</van-tag>
              <van-tag v-if="!item.is_active" type="danger" size="small">禁用</van-tag>
            </div>
            <div class="text-sm text-gray-500 mt-1">{{ item.name }}</div>
          </template>
          <template #label>
            <div class="text-xs text-gray-400 mt-1">
              效率: {{ (item.efficiency * 100).toFixed(0) }}% |
              设备: {{ item.equipment_count }} 台 |
              人员: {{ item.labor_count }} 人
              <span v-if="item.is_esd"> | ESD</span>
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
    </van-list>

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
            <van-select v-model="editing.wc_type" class="w-full">
              <van-option v-for="opt in WC_TYPE_OPTIONS" :key="opt.value" :value="opt.value" :label="opt.label" />
            </van-select>
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
  </div>
</template>
