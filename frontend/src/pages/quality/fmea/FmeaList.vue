<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showConfirmDialog, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

interface FmeaDocument {
  id: number
  doc_no: string
  fmea_type: string
  title: string
  product_id: number | null
  process_id: number | null
  project_id: number | null
  version: string
  status: string
  is_latest: boolean
  source_doc_id: number | null
  rpn_threshold: number
  remark: string | null
  created_by: number
  published_at: string | null
  created_at: string
  updated_at: string
}

const router = useRouter()
const list = ref<FmeaDocument[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const statusFilter = ref('')
const typeFilter = ref('')
const showCreateDialog = ref(false)
const form = ref({
  fmea_type: 'dfmea',
  title: '',
  product_id: null as number | null,
  process_id: null as number | null,
  project_id: null as number | null,
  source_doc_id: null as number | null,
  rpn_threshold: 100,
  remark: '',
})
const submitting = ref(false)

const typeOptions = [
  { value: 'dfmea', label: 'DFMEA' },
  { value: 'pfmea', label: 'PFMEA' },
  { value: 'efmea', label: 'EFMEA' },
]

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'revised', label: '修订中' },
]

const statusMap: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  revised: '修订中',
}

const typeLabelMap: Record<string, string> = {
  dfmea: 'DFMEA',
  pfmea: 'PFMEA',
  efmea: 'EFMEA',
}

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (statusFilter.value) params.status = statusFilter.value
  if (typeFilter.value) params.fmea_type = typeFilter.value

  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<FmeaDocument>>('/fmea/documents', { ...params, ...p })
  })
  list.value = (items as unknown) as FmeaDocument[]
}

function onFilterChange() {
  resetPage()
  loadData()
}

function openCreate() {
  form.value = {
    fmea_type: 'dfmea',
    title: '',
    product_id: null,
    process_id: null,
    project_id: null,
    source_doc_id: null,
    rpn_threshold: 100,
    remark: '',
  }
  showCreateDialog.value = true
}

async function handleCreate() {
  if (!form.value.title) {
    showToast('请输入FMEA标题')
    return
  }
  submitting.value = true
  try {
    await post('/fmea/documents', form.value)
    showToast('创建成功')
    showCreateDialog.value = false
    loadData()
  } catch {
    showToast('创建失败')
  } finally {
    submitting.value = false
  }
}

async function handlePublish(item: FmeaDocument) {
  try {
    await post(`/fmea/documents/${item.id}/publish`)
    showToast('已发布')
    loadData()
  } catch {
    showToast('发布失败')
  }
}

async function handleRevise(item: FmeaDocument) {
  try {
    await post(`/fmea/documents/${item.id}/revise`)
    showToast('已创建修订版')
    loadData()
  } catch {
    showToast('修订失败')
  }
}

async function handleDelete(item: FmeaDocument) {
  try {
    await showConfirmDialog({ message: `确定删除FMEA文档「${item.title}」？` })
    await del(`/fmea/documents/${item.id}`)
    showToast('删除成功')
    loadData()
  } catch {
    // cancelled
  }
}

function goEdit(item: FmeaDocument) {
  router.push(`/quality/fmea/${item.id}/edit`)
}

function goActions(item: FmeaDocument) {
  router.push(`/quality/fmea/${item.id}/actions`)
}

function goControlPlan(item: FmeaDocument) {
  router.push(`/quality/fmea/${item.id}/control-plan`)
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="FMEA管理" right-text="新建文档" @click-right="openCreate" />

    <div style="display:flex; gap:8px; margin:12px; flex-wrap:wrap;">
      <van-tag
        v-for="opt in typeOptions" :key="opt.value"
        :type="typeFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="typeFilter = typeFilter === opt.value ? '' : opt.value; onFilterChange()"
      >{{ opt.label }}</van-tag>
      <van-tag
        v-for="opt in statusOptions" :key="opt.value"
        :type="statusFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="statusFilter = statusFilter === opt.value ? '' : opt.value; onFilterChange()"
      >{{ opt.label }}</van-tag>
    </div>

    <van-list v-model:loading="loading" :finished="!total || list.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          <span>{{ item.title }}</span>
          <van-tag
            :type="item.status === 'published' ? 'success' : item.status === 'revised' ? 'warning' : 'default'"
            style="margin-left:6px"
          >{{ statusMap[item.status] || item.status }}</van-tag>
          <van-tag plain style="margin-left:4px">{{ typeLabelMap[item.fmea_type] || item.fmea_type }}</van-tag>
        </template>
        <template #label>
          <div>文档号: {{ item.doc_no }} | 版本: {{ item.version }}</div>
          <div v-if="item.product_id">产品ID: {{ item.product_id }}</div>
          <div>RPN阈值: {{ item.rpn_threshold }}</div>
        </template>
        <template #value>
          <div style="display:flex; gap:4px; flex-wrap:wrap">
            <van-button size="mini" plain type="primary" @click="goEdit(item)">编辑</van-button>
            <van-button size="mini" plain type="success" @click="goActions(item)">措施</van-button>
            <van-button size="mini" plain type="warning" @click="goControlPlan(item)">控制计划</van-button>
            <van-button v-if="item.status === 'draft'" size="mini" plain type="primary" @click="handlePublish(item)">发布</van-button>
            <van-button v-if="item.status === 'published'" size="mini" plain type="primary" @click="handleRevise(item)">修订</van-button>
            <van-button size="mini" plain type="danger" @click="handleDelete(item)">删除</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && list.length === 0" description="暂无FMEA文档" />

    <!-- 新建弹窗 -->
    <van-dialog v-model:show="showCreateDialog" title="新建FMEA文档" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleCreate(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model="form.title" label="文档标题" placeholder="必填" :rules="[{ required: true }]" />
        <van-field name="fmea_type" label="FMEA类型">
          <template #input>
            <van-radio-group v-model="form.fmea_type" direction="horizontal">
              <van-radio v-for="t in typeOptions" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field label="产品ID" type="digit" placeholder="选填">
          <template #input>
            <input v-model.number="form.product_id" type="number" style="width:100%;border:none;outline:none;background:transparent" />
          </template>
        </van-field>
        <van-field label="工序ID" type="digit" placeholder="选填">
          <template #input>
            <input v-model.number="form.process_id" type="number" style="width:100%;border:none;outline:none;background:transparent" />
          </template>
        </van-field>
        <van-field v-model.number="form.rpn_threshold" label="RPN阈值" type="digit" placeholder="100" />
        <van-field v-model="form.remark" label="备注" type="textarea" rows="2" placeholder="选填" />
      </div>
    </van-dialog>
  </div>
</template>
