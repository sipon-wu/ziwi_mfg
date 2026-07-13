<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'

interface Operation {
  id: number
  code: string
  name: string
  op_type: string
  setup_time: number
  unit_time: number
  labor_cert: string | null
  equip_req: string | null
  material_reqs: string | null
  sop_refs: string | null
  env_req: string | null
  remark: string | null
  is_active: boolean
  created_at: string
}

const OP_TYPE_OPTIONS = [
  { value: 'machining', label: '机加工' },
  { value: 'assembly', label: '装配' },
  { value: 'heat_treat', label: '热处理' },
  { value: 'surface_treat', label: '表面处理' },
  { value: 'inspect', label: '检验' },
  { value: 'pack', label: '包装' },
  { value: 'reaction', label: '反应' },
  { value: 'blend', label: '混合' },
  { value: 'separation', label: '分离' },
  { value: 'filling', label: '灌装' },
  { value: 'transport', label: '转运' },
]

const list = ref<Operation[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const finished = ref(false)
const keyword = ref('')
const opTypeFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<Operation>>({})
const isEdit = ref(false)

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: page.value, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (opTypeFilter.value) params.op_type = opTypeFilter.value
    const res = await get('/operations', { params })
    if (page.value === 1) {
      list.value = res.items
    } else {
      list.value.push(...res.items)
    }
    total.value = res.total
    finished.value = list.value.length >= total.value
  } catch (e: any) {
    showToast(e?.detail?.message || '获取工序列表失败')
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
  opTypeFilter.value = ''
  onSearch()
}

function openCreate() {
  isEdit.value = false
  editing.value = {
    code: '',
    name: '',
    op_type: 'machining',
    setup_time: 0,
    unit_time: 0,
    labor_cert: null,
    equip_req: null,
    material_reqs: null,
    sop_refs: null,
    env_req: null,
    remark: null,
    is_active: true,
  }
  showDialog_.value = true
}

function openEdit(item: Operation) {
  isEdit.value = true
  editing.value = { ...item }
  showDialog_.value = true
}

async function handleSave() {
  try {
    const data = { ...editing.value }
    if (isEdit.value) {
      await put(`/operations/${data.id}`, data)
      showToast('工序更新成功')
    } else {
      await post('/operations', data)
      showToast('工序创建成功')
    }
    showDialog_.value = false
    page.value = 1
    fetchData()
  } catch (e: any) {
    showToast(e?.detail?.message || '操作失败')
  }
}

async function handleDelete(item: Operation) {
  showDialog({
    title: '确认删除',
    message: `确定删除工序「${item.code} - ${item.name}」？`,
    showCancelButton: true,
  }).then(async (action: string) => {
    if (action === 'confirm') {
      try {
        await del(`/operations/${item.id}`)
        showToast('删除成功')
        page.value = 1
        fetchData()
      } catch (e: any) {
        showToast(e?.detail?.message || '删除失败')
      }
    }
  })
}

function getOpTypeLabel(v: string): string {
  return OP_TYPE_OPTIONS.find(o => o.value === v)?.label || v
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
          placeholder="搜索工序编码/名称"
          clearable
          @keyup.enter="onSearch"
        />
      </div>
      <div class="w-40">
        <SelectField v-model="opTypeFilter" :options="OP_TYPE_OPTIONS" placeholder="工序类型" clearable />
      </div>
      <div class="flex gap-2">
        <van-button type="primary" size="small" @click="onSearch">搜索</van-button>
        <van-button plain size="small" @click="onReset">重置</van-button>
        <van-button type="success" size="small" @click="openCreate">新增工序</van-button>
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
              <van-tag type="primary" size="small">{{ getOpTypeLabel(item.op_type) }}</van-tag>
              <van-tag v-if="!item.is_active" type="danger" size="small">禁用</van-tag>
            </div>
            <div class="text-sm text-gray-500 mt-1">{{ item.name }}</div>
          </template>
          <template #label>
            <div class="text-xs text-gray-400 mt-1">
              准备: {{ item.setup_time }}min | 单件: {{ item.unit_time }}min/件
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
      :title="isEdit ? '编辑工序' : '新增工序'"
      show-cancel-button
      @confirm="handleSave"
      class="!w-[500px]"
    >
      <div class="p-4 space-y-3">
        <van-field v-model="editing.code" label="工序编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="工序名称" required placeholder="请输入名称" />
        <van-field label="工序类型" required>
          <template #input>
            <SelectField v-model="editing.op_type" :options="OP_TYPE_OPTIONS" class="w-full" />
          </template>
        </van-field>
        <van-field v-model.number="editing.setup_time" label="准备时间(min)" type="number" placeholder="0" />
        <van-field v-model.number="editing.unit_time" label="单件时间(min/件)" type="number" placeholder="0" />
        <van-field v-model="editing.remark" label="备注" type="textarea" rows="2" placeholder="可选" />
      </div>
    </van-dialog>
  </div>
</template>
