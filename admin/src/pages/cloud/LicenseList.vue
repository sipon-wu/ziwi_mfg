<template>
  <div class="license-list-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>许可证管理</h2>
      <button class="btn-primary" @click="openCreateModal">+ 发放许可证</button>
    </div>

    <!-- 搜索 -->
    <div class="search-bar">
      <input
        v-model="searchKeyword"
        placeholder="搜索租户名称..."
        @input="onSearch"
      />
      <select v-model="statusFilter" class="form-select" style="flex:none;width:140px;padding:7px 12px;border:1px solid var(--ziwi-border);border-radius:var(--ziwi-radius-sm);font-size:var(--ziwi-font-size-md);outline:none;background:var(--ziwi-bg-white)" @change="onFilter">
        <option value="">全部状态</option>
        <option value="active">活跃</option>
        <option value="expired">已过期</option>
        <option value="pending">待激活</option>
      </select>
    </div>

    <!-- 加载 -->
    <div class="loading-container" v-if="loading">
      <div class="loading-spinner"></div>
      <span>加载中...</span>
    </div>

    <!-- 错误 -->
    <div class="error-container" v-if="errorMsg">
      <div class="error-icon">⚠</div>
      <span>{{ errorMsg }}</span>
      <button class="btn btn-sm" style="margin-top: 12px" @click="fetchLicenses">重试</button>
    </div>

    <!-- 表格 -->
    <table class="ziwi-table" v-if="!loading && !errorMsg">
      <thead>
        <tr>
          <th>ID</th>
          <th>租户</th>
          <th>套餐类型</th>
          <th>开始时间</th>
          <th>到期时间</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="license in licenses" :key="license.id">
          <td>{{ license.id }}</td>
          <td><strong>{{ license.tenant_name }}</strong></td>
          <td>{{ planLabel(license.plan_type) }}</td>
          <td>{{ formatDate(license.start_date) }}</td>
          <td>{{ formatDate(license.end_date) }}</td>
          <td>
            <span class="status-tag" :class="license.status">
              {{ statusLabel(license.status) }}
            </span>
          </td>
          <td>
            <div class="table-actions">
              <button
                v-if="license.status === 'active'"
                class="btn-primary btn-sm"
                @click="handleRenew(license)"
              >
                续期
              </button>
            </div>
          </td>
        </tr>
        <tr v-if="licenses.length === 0">
          <td colspan="7">
            <div class="empty-state">
              <div class="empty-icon">🔑</div>
              <span>暂无许可证数据</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 分页 -->
    <div class="pagination" v-if="total > pageSize">
      <span class="page-info">共 {{ total }} 条</span>
      <button :disabled="currentPage <= 1" @click="goPage(currentPage - 1)">上一页</button>
      <button
        v-for="p in pageNumbers"
        :key="p"
        :class="{ active: p === currentPage }"
        @click="goPage(p)"
      >
        {{ p }}
      </button>
      <button :disabled="currentPage >= totalPages" @click="goPage(currentPage + 1)">下一页</button>
    </div>

    <!-- ===== 发放许可证弹窗 ===== -->
    <div class="modal-overlay" v-if="showModal" @click.self="closeModal">
      <div class="modal-content">
        <h3>发放许可证</h3>
        <div class="form-group">
          <label>选择租户 *</label>
          <select v-model="form.tenant_id">
            <option value="">请选择租户</option>
            <option v-for="t in tenantOptions" :key="t.id" :value="t.id">
              {{ t.name }} ({{ t.code }})
            </option>
          </select>
        </div>
        <div class="form-group">
          <label>套餐类型 *</label>
          <select v-model="form.plan_type">
            <option value="">请选择套餐</option>
            <option value="basic">基础版</option>
            <option value="pro">专业版</option>
            <option value="enterprise">企业版</option>
            <option value="trial">试用版</option>
          </select>
        </div>
        <div class="form-group">
          <label>开始时间</label>
          <input v-model="form.start_date" type="date" />
        </div>
        <div class="form-group">
          <label>到期时间 *</label>
          <input v-model="form.end_date" type="date" />
        </div>
        <div v-if="modalError" class="login-error" style="margin-bottom: 0">{{ modalError }}</div>
        <div class="modal-actions">
          <button class="btn-outline" @click="closeModal">取消</button>
          <button class="btn-primary" @click="handleSave" :disabled="saving">
            {{ saving ? '发放中...' : '确认发放' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getList, post, put } from '@/api/client'
import type { License, Tenant } from '@/types/api'

const loading = ref(true)
const errorMsg = ref('')

const licenses = ref<License[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 15

const searchKeyword = ref('')
const statusFilter = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const pageNumbers = computed(() => {
  const pages: number[] = []
  const total = totalPages.value
  const current = currentPage.value
  let start = Math.max(1, current - 2)
  let end = Math.min(total, current + 2)
  if (end - start < 4) {
    if (start === 1) end = Math.min(total, start + 4)
    else start = Math.max(1, end - 4)
  }
  for (let i = start; i <= end; i++) pages.push(i)
  return pages
})

/* ===== API ===== */
async function fetchLicenses(): Promise<void> {
  loading.value = true
  errorMsg.value = ''

  try {
    const params: Record<string, any> = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
    if (statusFilter.value) params.status = statusFilter.value

    const result = await getList<License>('/licenses', params)
    licenses.value = result.items
    total.value = result.total
  } catch (err: any) {
    errorMsg.value = err?.response?.data?.message || err?.message || '获取许可证列表失败'
  } finally {
    loading.value = false
  }
}

function onSearch(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchLicenses()
  }, 400)
}

function onFilter(): void {
  currentPage.value = 1
  fetchLicenses()
}

function goPage(page: number): void {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  fetchLicenses()
}

/* ===== 格式化 ===== */
function statusLabel(status: string): string {
  const map: Record<string, string> = {
    active: '活跃',
    expired: '已过期',
    pending: '待激活',
  }
  return map[status] || status
}

function planLabel(plan: string): string {
  const map: Record<string, string> = {
    basic: '基础版',
    pro: '专业版',
    enterprise: '企业版',
    trial: '试用版',
  }
  return map[plan] || plan
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  try {
    const date = new Date(dateStr)
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  } catch {
    return dateStr
  }
}

/* ===== 弹窗 ===== */
const showModal = ref(false)
const saving = ref(false)
const modalError = ref('')
const tenantOptions = ref<Tenant[]>([])

const form = ref({
  tenant_id: 0,
  plan_type: '',
  start_date: '',
  end_date: '',
})

async function openCreateModal(): Promise<void> {
  modalError.value = ''
  form.value = { tenant_id: 0, plan_type: '', start_date: '', end_date: '' }

  // 加载租户列表供选择
  try {
    const result = await getList<Tenant>('/tenants', { page: 1, page_size: 999 })
    tenantOptions.value = result.items
  } catch {
    tenantOptions.value = []
  }

  showModal.value = true
}

function closeModal(): void {
  showModal.value = false
}

async function handleSave(): Promise<void> {
  if (!form.value.tenant_id || !form.value.plan_type || !form.value.end_date) {
    modalError.value = '请填写必填项'
    return
  }

  saving.value = true
  modalError.value = ''

  try {
    await post<License>('/licenses', {
      tenant_id: form.value.tenant_id,
      plan_type: form.value.plan_type,
      start_date: form.value.start_date || undefined,
      end_date: form.value.end_date,
    })
    closeModal()
    fetchLicenses()
  } catch (err: any) {
    modalError.value = err?.response?.data?.message || err?.message || '发放失败'
  } finally {
    saving.value = false
  }
}

/* ===== 续期 ===== */
async function handleRenew(license: License): Promise<void> {
  const newEndDate = prompt(
    `为租户「${license.tenant_name}」续期许可证，请输入新的到期日期 (YYYY-MM-DD)：`,
    license.end_date
  )
  if (!newEndDate) return

  try {
    await put<License>(`/licenses/${license.id}/renew`, { end_date: newEndDate })
    fetchLicenses()
  } catch (err: any) {
    alert(err?.response?.data?.message || err?.message || '续期失败')
  }
}

onMounted(fetchLicenses)
</script>

<style scoped>
.license-list-page {
  max-width: 1100px;
}

.table-actions {
  display: flex;
  gap: 6px;
}
</style>
