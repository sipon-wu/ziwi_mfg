<template>
  <div class="token-list-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>Token / API Key 管理</h2>
      <button class="btn-primary" @click="openCreateModal">+ 新建 API Key</button>
    </div>

    <!-- 搜索 -->
    <div class="search-bar">
      <input
        v-model="searchKeyword"
        placeholder="搜索租户名称..."
        @input="onSearch"
      />
      <select v-model="statusFilter" style="flex:none;width:140px;padding:7px 12px;border:1px solid var(--ziwi-border);border-radius:var(--ziwi-radius-sm);font-size:var(--ziwi-font-size-md);outline:none;background:var(--ziwi-bg-white)" @change="onFilter">
        <option value="">全部状态</option>
        <option value="active">活跃</option>
        <option value="revoked">已吊销</option>
      </select>
      <select v-model="typeFilter" style="flex:none;width:160px;padding:7px 12px;border:1px solid var(--ziwi-border);border-radius:var(--ziwi-radius-sm);font-size:var(--ziwi-font-size-md);outline:none;background:var(--ziwi-bg-white)" @change="onFilter">
        <option value="">全部类型</option>
        <option value="api_key">API Key</option>
        <option value="ai_token">AI 服务 Token</option>
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
      <button class="btn btn-sm" style="margin-top: 12px" @click="fetchTokens">重试</button>
    </div>

    <!-- 表格 -->
    <table class="ziwi-table" v-if="!loading && !errorMsg">
      <thead>
        <tr>
          <th>ID</th>
          <th>租户</th>
          <th>Key</th>
          <th>类型</th>
          <th>状态</th>
          <th>最后调用</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="token in tokens" :key="token.id">
          <td>{{ token.id }}</td>
          <td><strong>{{ token.tenant_name }}</strong></td>
          <td>
            <code class="key-display">{{ maskKey(token.key_prefix) }}</code>
          </td>
          <td>{{ tokenTypeLabel(token.token_type) }}</td>
          <td>
            <span class="status-tag" :class="token.status">
              {{ statusLabel(token.status) }}
            </span>
          </td>
          <td>{{ formatTime(token.last_called_at) }}</td>
          <td>
            <div class="table-actions">
              <button
                v-if="token.status === 'active'"
                class="btn-sm btn-danger"
                @click="handleRevoke(token)"
              >
                吊销
              </button>
              <span v-else class="text-muted">-</span>
            </div>
          </td>
        </tr>
        <tr v-if="tokens.length === 0">
          <td colspan="7">
            <div class="empty-state">
              <div class="empty-icon">🎫</div>
              <span>暂无 Token 数据</span>
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

    <!-- ===== 新建 API Key 弹窗 ===== -->
    <div class="modal-overlay" v-if="showModal" @click.self="closeModal">
      <div class="modal-content">
        <h3>新建 API Key</h3>
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
          <label>Token 类型 *</label>
          <select v-model="form.token_type">
            <option value="api_key">API Key</option>
            <option value="ai_token">AI 服务 Token</option>
          </select>
        </div>
        <div v-if="createdToken" class="token-result">
          <label>新生成的 Key：</label>
          <div class="token-value">
            <code>{{ createdToken }}</code>
          </div>
          <p class="token-warning">请立即复制保存，关闭后将无法再次查看完整 Key。</p>
        </div>
        <div v-if="modalError" class="login-error" style="margin-bottom: 0">{{ modalError }}</div>
        <div class="modal-actions">
          <button class="btn-outline" @click="closeModal">{{ createdToken ? '关闭' : '取消' }}</button>
          <button v-if="!createdToken" class="btn-primary" @click="handleSave" :disabled="saving">
            {{ saving ? '创建中...' : '确认创建' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getList, post, del } from '@/api/client'
import type { ApiToken, Tenant } from '@/types/api'

const loading = ref(true)
const errorMsg = ref('')

const tokens = ref<ApiToken[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 15

const searchKeyword = ref('')
const statusFilter = ref('')
const typeFilter = ref('')
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
async function fetchTokens(): Promise<void> {
  loading.value = true
  errorMsg.value = ''

  try {
    const params: Record<string, any> = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
    if (statusFilter.value) params.status = statusFilter.value
    if (typeFilter.value) params.token_type = typeFilter.value

    const result = await getList<ApiToken>('/tokens', params)
    tokens.value = result.items
    total.value = result.total
  } catch (err: any) {
    errorMsg.value = err?.response?.data?.message || err?.message || '获取 Token 列表失败'
  } finally {
    loading.value = false
  }
}

function onSearch(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchTokens()
  }, 400)
}

function onFilter(): void {
  currentPage.value = 1
  fetchTokens()
}

function goPage(page: number): void {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  fetchTokens()
}

/* ===== 格式化 ===== */
function maskKey(prefix: string): string {
  if (!prefix) return '***'
  return prefix + '***' + prefix.slice(-4)
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    active: '活跃',
    revoked: '已吊销',
  }
  return map[status] || status
}

function tokenTypeLabel(type: string): string {
  const map: Record<string, string> = {
    api_key: 'API Key',
    ai_token: 'AI 服务 Token',
  }
  return map[type] || type
}

function formatTime(dateStr: string): string {
  if (!dateStr) return '从未调用'
  try {
    const date = new Date(dateStr)
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    const h = String(date.getHours()).padStart(2, '0')
    const min = String(date.getMinutes()).padStart(2, '0')
    return `${y}-${m}-${d} ${h}:${min}`
  } catch {
    return dateStr
  }
}

/* ===== 弹窗 ===== */
const showModal = ref(false)
const saving = ref(false)
const modalError = ref('')
const tenantOptions = ref<Tenant[]>([])
const createdToken = ref('')

const form = ref({
  tenant_id: 0,
  token_type: 'api_key',
})

async function openCreateModal(): Promise<void> {
  modalError.value = ''
  createdToken.value = ''
  form.value = { tenant_id: 0, token_type: 'api_key' }

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
  createdToken.value = ''
}

async function handleSave(): Promise<void> {
  if (!form.value.tenant_id || !form.value.token_type) {
    modalError.value = '请选择租户和Token类型'
    return
  }

  saving.value = true
  modalError.value = ''

  try {
    const result = await post<{ key: string }>('/tokens', {
      tenant_id: form.value.tenant_id,
      token_type: form.value.token_type,
    })
    createdToken.value = result.key
    fetchTokens()
  } catch (err: any) {
    modalError.value = err?.response?.data?.message || err?.message || '创建失败'
  } finally {
    saving.value = false
  }
}

/* ===== 吊销 ===== */
async function handleRevoke(token: ApiToken): Promise<void> {
  if (!confirm(`确认吊销租户「${token.tenant_name}」的 Token (ID: ${token.id}) 吗？此操作不可撤销。`)) return

  try {
    await del(`/tokens/${token.id}`)
    fetchTokens()
  } catch (err: any) {
    alert(err?.response?.data?.message || err?.message || '吊销失败')
  }
}

onMounted(fetchTokens)
</script>

<style scoped>
.token-list-page {
  max-width: 1100px;
}

.table-actions {
  display: flex;
  gap: 6px;
}

.key-display {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  background: var(--ziwi-bg-light);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-secondary);
  letter-spacing: 0.5px;
}

.text-muted {
  color: var(--ziwi-text-muted);
  font-size: var(--ziwi-font-size-md);
}

.token-result {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  border-radius: var(--ziwi-radius-md);
  padding: 12px;
  margin-bottom: 12px;
}

.token-result label {
  font-size: var(--ziwi-font-size-md);
  font-weight: 500;
  display: block;
  margin-bottom: 8px;
  color: var(--ziwi-text-regular);
}

.token-value {
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  padding: 8px 12px;
  margin-bottom: 8px;
  word-break: break-all;
}

.token-value code {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-primary);
}

.token-warning {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-warning);
  margin: 0;
}
</style>
