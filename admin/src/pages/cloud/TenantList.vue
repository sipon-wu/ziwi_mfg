<template>
  <div class="tenant-list-page">
    <!-- 页面标题区 -->
    <div class="page-header">
      <h2>租户管理</h2>
      <button class="btn-primary" @click="openCreateModal">+ 新建租户</button>
    </div>

    <!-- 搜索/筛选栏 -->
    <div class="search-bar">
      <input
        v-model="searchKeyword"
        placeholder="搜索租户名称..."
        @input="onSearch"
      />
      <select v-model="statusFilter" class="form-select" style="flex:none;width:140px;padding:7px 12px;border:1px solid var(--ziwi-border);border-radius:var(--ziwi-radius-sm);font-size:var(--ziwi-font-size-md);outline:none;background:var(--ziwi-bg-white)" @change="onFilter">
        <option value="">全部状态</option>
        <option value="active">活跃</option>
        <option value="trial">试用</option>
        <option value="expired">已过期</option>
        <option value="disabled">已停用</option>
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
      <button class="btn btn-sm" style="margin-top: 12px" @click="fetchTenants">重试</button>
    </div>

    <!-- 表格 -->
    <table class="ziwi-table" v-if="!loading && !errorMsg">
      <thead>
        <tr>
          <th>ID</th>
          <th>租户名称</th>
          <th>编码</th>
          <th>联系人</th>
          <th>状态</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="tenant in tenants" :key="tenant.id">
          <td>{{ tenant.id }}</td>
          <td><strong>{{ tenant.name }}</strong></td>
          <td><code>{{ tenant.code }}</code></td>
          <td>
            <div>{{ tenant.contact_person }}</div>
            <div style="font-size: var(--ziwi-font-size-sm); color: var(--ziwi-text-muted)">{{ tenant.contact_email }}</div>
          </td>
          <td>
            <span class="status-tag" :class="tenant.status">
              {{ statusLabel(tenant.status) }}
            </span>
          </td>
          <td>{{ formatTime(tenant.created_at) }}</td>
          <td>
            <div class="table-actions">
              <button class="btn-link" @click="openEditModal(tenant)">编辑</button>
              <button
                class="btn-sm"
                :class="tenant.status === 'disabled' ? 'btn-primary' : 'btn-danger'"
                @click="handleToggleStatus(tenant)"
              >
                {{ tenant.status === 'disabled' ? '启用' : '停用' }}
              </button>
            </div>
          </td>
        </tr>
        <tr v-if="tenants.length === 0">
          <td colspan="7">
            <div class="empty-state">
              <div class="empty-icon">📭</div>
              <span>暂无租户数据</span>
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

    <!-- ====== 新建/编辑租户弹窗 ====== -->
    <div class="modal-overlay" v-if="showModal" @click.self="closeModal">
      <div class="modal-content">
        <h3>{{ editingTenant ? '编辑租户' : '新建租户' }}</h3>
        <div class="form-group">
          <label>租户名称 *</label>
          <input v-model="form.name" placeholder="请输入租户名称" />
        </div>
        <div class="form-group">
          <label>编码 *</label>
          <input v-model="form.code" placeholder="唯一编码，如：ziwi-001" :disabled="!!editingTenant" />
        </div>
        <div class="form-group">
          <label>联系人</label>
          <input v-model="form.contact_person" placeholder="联系人姓名" />
        </div>
        <div class="form-group">
          <label>联系邮箱</label>
          <input v-model="form.contact_email" placeholder="联系人邮箱" type="email" />
        </div>
        <div class="form-group" v-if="editingTenant">
          <label>状态</label>
          <select v-model="form.status">
            <option value="active">活跃</option>
            <option value="trial">试用</option>
            <option value="expired">已过期</option>
            <option value="disabled">已停用</option>
          </select>
        </div>
        <div v-if="modalError" class="login-error" style="margin-bottom: 0">{{ modalError }}</div>
        <div class="modal-actions">
          <button class="btn-outline" @click="closeModal">取消</button>
          <button class="btn-primary" @click="handleSave" :disabled="saving">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getList, post, put } from '@/api/client'
import type { Tenant } from '@/types/api'

const loading = ref(true)
const errorMsg = ref('')

const tenants = ref<Tenant[]>([])
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

async function fetchTenants(): Promise<void> {
  loading.value = true
  errorMsg.value = ''

  try {
    const params: Record<string, any> = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (searchKeyword.value.trim()) {
      params.keyword = searchKeyword.value.trim()
    }
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    const result = await getList<Tenant>('/tenants', params)
    tenants.value = result.items
    total.value = result.total
  } catch (err: any) {
    errorMsg.value = err?.response?.data?.message || err?.message || '获取租户列表失败'
  } finally {
    loading.value = false
  }
}

function onSearch(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchTenants()
  }, 400)
}

function onFilter(): void {
  currentPage.value = 1
  fetchTenants()
}

function goPage(page: number): void {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  fetchTenants()
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    active: '活跃',
    trial: '试用',
    expired: '已过期',
    disabled: '已停用',
  }
  return map[status] || status
}

function formatTime(dateStr: string): string {
  if (!dateStr) return ''
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

/* ===== 弹窗相关 ===== */
const showModal = ref(false)
const editingTenant = ref<Tenant | null>(null)
const saving = ref(false)
const modalError = ref('')

const form = ref({
  name: '',
  code: '',
  contact_person: '',
  contact_email: '',
  status: 'active' as string,
})

function openCreateModal(): void {
  editingTenant.value = null
  form.value = { name: '', code: '', contact_person: '', contact_email: '', status: 'active' }
  modalError.value = ''
  showModal.value = true
}

function openEditModal(tenant: Tenant): void {
  editingTenant.value = tenant
  form.value = {
    name: tenant.name,
    code: tenant.code,
    contact_person: tenant.contact_person,
    contact_email: tenant.contact_email,
    status: tenant.status,
  }
  modalError.value = ''
  showModal.value = true
}

function closeModal(): void {
  showModal.value = false
  editingTenant.value = null
  modalError.value = ''
}

async function handleSave(): Promise<void> {
  if (!form.value.name.trim() || !form.value.code.trim()) {
    modalError.value = '名称和编码为必填项'
    return
  }

  saving.value = true
  modalError.value = ''

  try {
    if (editingTenant.value) {
      await put<Tenant>(`/tenants/${editingTenant.value.id}`, form.value)
    } else {
      await post<Tenant>('/tenants', form.value)
    }
    closeModal()
    fetchTenants()
  } catch (err: any) {
    modalError.value = err?.response?.data?.message || err?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

/* ===== 停用/启用 ===== */
async function handleToggleStatus(tenant: Tenant): Promise<void> {
  const action = tenant.status === 'disabled' ? '启用' : '停用'
  if (!confirm(`确认${action}租户「${tenant.name}」吗？`)) return

  try {
    const newStatus = tenant.status === 'disabled' ? 'active' : 'disabled'
    await put<Tenant>(`/tenants/${tenant.id}/status`, { status: newStatus })
    fetchTenants()
  } catch (err: any) {
    alert(err?.response?.data?.message || err?.message || '操作失败')
  }
}

onMounted(fetchTenants)
</script>

<style scoped>
.tenant-list-page {
  max-width: 1100px;
}

.table-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  background: var(--ziwi-bg-light);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-secondary);
}
</style>
