<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog, showDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

interface PpapSubmission {
  id: number
  submission_no: string
  product_id: number
  customer_id: number
  level_no: number
  version: number
  status: string
  submitted_at: string | null
  approved_at: string | null
  change_note: string | null
  due_reminder: boolean
  remark: string | null
  created_at: string
  updated_at: string
}

interface PpapLevel {
  id: number
  level_no: number
  level_name: string
}

interface PpapElement {
  id: number
  element_code: string
  element_name: string
  description: string | null
  is_required: boolean
  sort_order: number
  level_no: number
  has_template: boolean
}

interface SubmissionItem {
  id: number
  element_code: string
  element_name: string
  is_required: boolean
  status: string
  file_path: string | null
  file_name: string | null
  assignee_id: number | null
  remark: string | null
}

interface SubmissionDetail extends PpapSubmission {
  items: SubmissionItem[]
}

const list = ref<PpapSubmission[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const levels = ref<PpapLevel[]>([])
const statusFilter = ref('')
const showCreateDialog = ref(false)
const showDetailDialog = ref(false)
const selectedSubmission = ref<SubmissionDetail | null>(null)
const buildForm = ref({
  product_id: 0,
  customer_id: 0,
  level_no: 1,
  change_note: '',
})
const submitting = ref(false)
const approveComment = ref('')

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'submitted', label: '已提交' },
  { value: 'approved', label: '已批准' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'conditional', label: '有条件批准' },
]

const statusMap: Record<string, string> = {
  draft: '草稿',
  submitted: '已提交',
  approved: '已批准',
  rejected: '已拒绝',
  conditional: '有条件批准',
}

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (statusFilter.value) params.status = statusFilter.value

  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<PpapSubmission>>('/ppap/submissions', { ...params, ...p })
  })
  list.value = (items as unknown) as PpapSubmission[]
}

async function loadLevels() {
  try {
    const res = await get<PaginatedResponse<PpapLevel>>('/ppap/levels', { page_size: 100 })
    levels.value = res.items || []
  } catch {
    console.warn('[PpapSubmissions] 获取等级列表失败')
  }
}

function onStatusChange() {
  resetPage()
  loadData()
}

function openCreate() {
  buildForm.value = { product_id: 0, customer_id: 0, level_no: 1, change_note: '' }
  showCreateDialog.value = true
}

async function handleBuild() {
  if (!buildForm.value.product_id || !buildForm.value.customer_id) {
    showToast('请填写产品和客户ID')
    return
  }
  submitting.value = true
  try {
    await post('/ppap/submissions/build', buildForm.value)
    showToast('提交包已构建')
    showCreateDialog.value = false
    loadData()
  } catch {
    showToast('构建失败')
  } finally {
    submitting.value = false
  }
}

async function viewDetail(item: PpapSubmission) {
  try {
    const detail = await get<SubmissionDetail>(`/ppap/submissions/${item.id}`)
    selectedSubmission.value = detail
    showDetailDialog.value = true
  } catch {
    showToast('获取详情失败')
  }
}

async function handleSubmitApproval(item: PpapSubmission) {
  try {
    await post(`/ppap/submissions/${item.id}/submit`)
    showToast('已提交审批')
    loadData()
  } catch {
    showToast('提交失败')
  }
}

async function handleApprove(status: 'approved' | 'rejected' | 'conditional') {
  if (!selectedSubmission.value) return
  try {
    await put(`/ppap/submissions/${selectedSubmission.value.id}/approve`, {
      status,
      comment: approveComment.value || undefined,
    })
    showToast(status === 'approved' ? '已批准' : status === 'rejected' ? '已拒绝' : '有条件批准')
    showDetailDialog.value = false
    loadData()
  } catch {
    showToast('操作失败')
  }
}

async function handleResubmit(item: PpapSubmission) {
  try {
    await post(`/ppap/submissions/${item.id}/submit`)
    showToast('已重新提交')
    loadData()
  } catch {
    showToast('重新提交失败')
  }
}

onMounted(() => {
  loadData()
  loadLevels()
})
</script>

<template>
  <div>
    <van-nav-bar title="PPAP提交管理" right-text="构建提交" @click-right="openCreate" />

    <div style="display:flex; gap:8px; margin:12px; flex-wrap:wrap;">
      <van-tag v-for="opt in statusOptions" :key="opt.value"
        :type="statusFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="statusFilter = opt.value; onStatusChange()"
      >{{ opt.label }}</van-tag>
    </div>

    <van-list v-model:loading="loading" :finished="!total || list.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in list" :key="item.id" is-link @click="viewDetail(item)">
        <template #title>
          <span>{{ item.submission_no }}</span>
          <van-tag :type="item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'danger' : 'primary'" style="margin-left:6px">
            {{ statusMap[item.status] || item.status }}
          </van-tag>
        </template>
        <template #label>
          <div>产品ID: {{ item.product_id }} | 客户ID: {{ item.customer_id }} | 等级: {{ item.level_no }}级</div>
          <div>版本: V{{ item.version }} | {{ item.created_at }}</div>
        </template>
        <template #value v-if="item.status === 'rejected'">
          <van-button size="mini" type="primary" @click.stop="handleResubmit(item)">重新提交</van-button>
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && list.length === 0" description="暂无提交记录" />

    <!-- 构建提交弹窗 -->
    <van-dialog v-model:show="showCreateDialog" title="构建提交包" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleBuild(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model.number="buildForm.product_id" label="产品ID" type="digit" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model.number="buildForm.customer_id" label="客户ID" type="digit" placeholder="必填" :rules="[{ required: true }]" />
        <van-field name="level_no" label="PPAP等级">
          <template #input>
            <van-picker
              :columns="levels.map(l => ({ text: `${l.level_no}级 - ${l.level_name}`, value: l.level_no }))"
              @confirm="(v:any) => buildForm.level_no = v.value"
            />
          </template>
        </van-field>
        <van-field v-model="buildForm.change_note" label="变更说明" type="textarea" rows="2" placeholder="选填" />
      </div>
    </van-dialog>

    <!-- 提交详情弹窗 -->
    <van-dialog v-model:show="showDetailDialog" title="提交详情" style="max-height:80vh;overflow-y:auto;">
      <div style="padding:16px">
        <div v-if="selectedSubmission">
          <van-cell-group title="基本信息">
            <van-cell title="提交编号" :value="selectedSubmission.submission_no" />
            <van-cell title="状态">
              <van-tag :type="selectedSubmission.status === 'approved' ? 'success' : selectedSubmission.status === 'rejected' ? 'danger' : 'primary'">
                {{ statusMap[selectedSubmission.status] || selectedSubmission.status }}
              </van-tag>
            </van-cell>
            <van-cell title="等级" :value="selectedSubmission.level_no + '级'" />
            <van-cell title="版本" :value="'V' + selectedSubmission.version" />
          </van-cell-group>

          <van-cell-group title="要素清单">
            <van-cell v-for="it in selectedSubmission.items" :key="it.id"
              :title="it.element_name"
              :label="`编码: ${it.element_code}`">
              <template #value>
                <van-tag :type="it.status === 'completed' ? 'success' : it.status === 'pending' ? 'warning' : 'default'">
                  {{ it.status === 'completed' ? '已上传' : it.status === 'pending' ? '待处理' : it.status }}
                </van-tag>
              </template>
            </van-cell>
            <van-cell v-if="!selectedSubmission.items?.length" title="暂无要素" />
          </van-cell-group>

          <!-- 审批操作 -->
          <div v-if="selectedSubmission.status === 'submitted'" style="margin-top:12px">
            <van-field v-model="approveComment" label="审批意见" type="textarea" rows="2" placeholder="选填" />
            <div style="display:flex; gap:8px; margin-top:8px">
              <van-button size="small" type="success" block @click="handleApprove('approved')">批准</van-button>
              <van-button size="small" type="danger" block @click="handleApprove('rejected')">拒绝</van-button>
              <van-button size="small" type="warning" block @click="handleApprove('conditional')">有条件批准</van-button>
            </div>
          </div>
        </div>
      </div>
    </van-dialog>
  </div>
</template>
