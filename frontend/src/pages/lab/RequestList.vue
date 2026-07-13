<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showDialog, showConfirmDialog } from 'vant'
import { listRequests, createRequest } from '@/api/lab'
import type { LabRequest } from '@/api/lab'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

const router = useRouter()
const rawRequests = ref<LabRequest[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const filterStatus = ref('')
const filterType = ref('')
const filterPriority = ref('')

// 高级检索 + 行展开
const cfg = getSearchConfig('lab/requests')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<LabRequest>(cfg)
const requests = computed<LabRequest[]>(() =>
  conditions.value.length ? applyFilter(rawRequests.value) : rawRequests.value,
)
const showSearch = ref(false)
const expandedId = ref<number | null>(null)
function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}
function onSearchSubmit(c: SearchCondition[]) {
  conditions.value = c
  showSearch.value = false
}
function onResetSubmit() {
  conditions.value = []
  showSearch.value = false
}
function condText(c: SearchCondition) {
  return describeCondition(c, cfg)
}

const typeOptions = [
  { value: '', text: '全部类型' },
  { value: 'mechanical', text: '力学性能' },
  { value: 'metallographic', text: '金相分析' },
  { value: 'chemical', text: '化学成分' },
  { value: 'dimensional', text: '尺寸测量' },
  { value: 'environmental', text: '环境试验' },
  { value: 'physical', text: '物理性能' },
  { value: 'aging', text: '老化试验' },
  { value: 'ndt', text: '无损检测' },
  { value: 'cleanliness', text: '洁净度' },
  { value: 'other', text: '其他' },
]

const statusOptions = [
  { value: '', text: '全部状态' },
  { value: 'pending', text: '待接收' },
  { value: 'received', text: '已接收' },
  { value: 'assigned', text: '已分派' },
  { value: 'in_progress', text: '进行中' },
  { value: 'reviewing', text: '审核中' },
  { value: 'done', text: '已完成' },
]

const priorityOptions = [
  { value: '', text: '全部优先级' },
  { value: 'high', text: '高' },
  { value: 'medium', text: '中' },
  { value: 'low', text: '低' },
]

const statusMap: Record<string, string> = {
  pending: '待接收', received: '已接收', assigned: '已分派',
  in_progress: '进行中', reviewing: '审核中', done: '已完成',
}

const typeMap: Record<string, string> = {
  mechanical: '力学', metallographic: '金相', chemical: '化学',
  dimensional: '尺寸', environmental: '环境', physical: '物理',
  aging: '老化', ndt: '无损', cleanliness: '洁净度', other: '其他',
}

const priorityMap: Record<string, string> = {
  high: '高', medium: '中', low: '低',
}

// 创建表单
const showCreate = ref(false)
const showTypePicker = ref(false)
const showPriorityPicker = ref(false)
const form = ref({
  title: '',
  request_type: 'mechanical',
  source_type: 'manual',
  priority: 'medium',
  description: '',
  sample_info: '',
  expected_date: '',
})

async function fetch() {
  loading.value = true
  try {
    const res = await listRequests({
      page: page.value,
      page_size: 20,
      status: filterStatus.value || undefined,
      request_type: filterType.value || undefined,
      priority: filterPriority.value || undefined,
    })
    rawRequests.value = res.items || []
    total.value = res.total || 0
  } finally { loading.value = false }
}

onMounted(fetch)

function viewDetail(id: number) { router.push(`/lab/${id}`) }
function goToStandards() { router.push('/lab/standards') }

async function handleCreate() {
  if (!form.value.title) { showToast('请输入委托标题'); return }
  try {
    const data: any = {
      title: form.value.title,
      request_type: form.value.request_type,
      source_type: form.value.source_type || 'manual',
      priority: form.value.priority,
    }
    if (form.value.description) data.description = form.value.description
    if (form.value.sample_info) {
      try { data.sample_info = JSON.parse(form.value.sample_info) }
      catch { data.sample_info = form.value.sample_info }
    }
    if (form.value.expected_date) data.expected_date = form.value.expected_date
    await createRequest(data)
    showToast('创建成功')
    showCreate.value = false
    form.value = { title: '', request_type: 'mechanical', source_type: 'manual', priority: 'medium', description: '', sample_info: '', expected_date: '' }
    fetch()
  } catch (e: any) {
    showToast(e.response?.data?.detail?.message || '创建失败')
  }
}
</script>

<template>
  <div>
    <van-nav-bar title="实验室管理" left-text="返回" @click-left="router.back()">
      <template #right>
        <van-button size="small" type="primary" @click="showCreate = true">新建委托</van-button>
        <van-button size="small" plain style="margin-left: 6px" @click="goToStandards">标准库</van-button>
      </template>
    </van-nav-bar>

    <!-- 筛选 -->
    <van-row gutter="8" style="padding: 8px">
      <van-col span="8">
        <van-dropdown-menu>
          <van-dropdown-item v-model="filterStatus" :options="statusOptions" @change="fetch" />
        </van-dropdown-menu>
      </van-col>
      <van-col span="8">
        <van-dropdown-menu>
          <van-dropdown-item v-model="filterType" :options="typeOptions" @change="fetch" />
        </van-dropdown-menu>
      </van-col>
      <van-col span="8">
        <van-dropdown-menu>
          <van-dropdown-item v-model="filterPriority" :options="priorityOptions" @change="fetch" />
        </van-dropdown-menu>
      </van-col>
    </van-row>

    <!-- 委托列表 -->
    <div style="padding:8px 16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <van-button size="small" icon="filter-o" @click="showSearch = true">高级检索</van-button>
      <van-tag
        v-for="c in conditions"
        :key="c.uid"
        type="primary"
        closeable
        size="medium"
        @close="removeCondition(c.uid)"
      >{{ condText(c) }}</van-tag>
      <van-button v-if="conditions.length" size="mini" plain type="primary" @click="onResetSubmit">清空</van-button>
    </div>
    <van-list v-model:loading="loading" :finished="requests.length >= total" @load="fetch">
      <van-cell v-for="item in requests" :key="item.id" @click="viewDetail(item.id)">
        <template #title>
          <span style="font-weight: bold">{{ item.request_no }}</span>
          <van-tag
            :type="item.status === 'done' ? 'success' : item.status === 'pending' ? 'warning' : 'primary'"
            style="margin-left: 6px"
          >
            {{ statusMap[item.status] || item.status }}
          </van-tag>
          <van-tag v-if="item.priority === 'high'" type="danger" style="margin-left: 4px">高优</van-tag>
        </template>
        <template #label>
          <div>{{ item.title }}</div>
          <div>{{ typeMap[item.request_type] || item.request_type }} | 优先级: {{ priorityMap[item.priority] || item.priority }}</div>
          <div v-if="item.source_type">来源: {{ item.source_type }}</div>
          <div style="font-size: 12px; color: #999">创建: {{ item.created_at?.slice(0, 10) }}</div>
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #right-icon>
          <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain style="margin-left:4px" @click.stop="toggleExpand(item.id)" />
        </template>
      </van-cell>
    </van-list>

    <!-- 创建弹窗 -->
    <van-dialog v-model:show="showCreate" title="新建实验委托" show-cancel-button @confirm="handleCreate">
      <van-form @submit.prevent="handleCreate">
        <van-cell-group inset>
          <van-field v-model="form.title" label="委托标题" placeholder="请输入" :rules="[{ required: true, message: '请输入标题' }]" />
          <van-field v-model="form.request_type" label="实验类型" placeholder="请选择" is-link readonly @click="showTypePicker = true" />
          <van-field v-model="form.priority" label="优先级" placeholder="请选择" is-link readonly @click="showPriorityPicker = true" />
          <van-field v-model="form.source_type" label="来源类型" placeholder="manual" />
          <van-field v-model="form.description" label="描述" type="textarea" rows="2" placeholder="委托描述" />
          <van-field v-model="form.sample_info" label="样品信息(JSON)" type="textarea" rows="2" placeholder='{"name":"样品1","qty":2}' />
          <van-field v-model="form.expected_date" label="期望完成" type="date" placeholder="选择日期" />
        </van-cell-group>
      </van-form>
    </van-dialog>

    <!-- 类型选择器 -->
    <van-action-sheet v-model:show="showTypePicker" :actions="typeOptions" @select="(a: any) => { form.request_type = a.value; showTypePicker = false }" />
    <van-action-sheet v-model:show="showPriorityPicker" :actions="priorityOptions.filter(o => o.value)" @select="(a: any) => { form.priority = a.value; showPriorityPicker = false }" />

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>

<script lang="ts">
export default { name: 'LabRequestList' }
</script>
