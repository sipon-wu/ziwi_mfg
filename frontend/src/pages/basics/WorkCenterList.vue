<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { get, post, put, del, errorText } from '@/api/client'
import ZiwiFormSheet from '@/components/ziwi/ZiwiFormSheet.vue'
import ZiwiListToolbar from '@/components/ziwi/ZiwiListToolbar.vue'
import ZiwiStateView from '@/components/ziwi/ZiwiStateView.vue'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

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

const rawList = ref<WorkCenter[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const wcTypeFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<WorkCenter>>({})
const isEdit = ref(false)

// 高级检索 + 行展开（并集方式多列并排）
const cfg = getSearchConfig('work-centers')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<WorkCenter>(cfg)
const list = computed<WorkCenter[]>(() =>
  conditions.value.length ? applyFilter(rawList.value) : rawList.value,
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

/* 空态区分两类（UE-12）：条件没命中 vs 本来就没有 */
const activeFilterTexts = computed<string[]>(() => {
  const out: string[] = []
  if (keyword.value) out.push(`关键词「${keyword.value}」`)
  if (wcTypeFilter.value) {
    const hit = WC_TYPE_OPTIONS.find((o) => o.value === wcTypeFilter.value)
    out.push(`类型「${hit?.label ?? wcTypeFilter.value}」`)
  }
  conditions.value.forEach((c) => out.push(condText(c)))
  return out
})
const isEmptyFiltered = computed(() => activeFilterTexts.value.length > 0)

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: 1, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (wcTypeFilter.value) params.wc_type = wcTypeFilter.value
    const res = await get('/work-centers', { params })
    rawList.value = res.items || []
  } catch (e: any) {
    showToast(errorText(e, '获取工作中心列表失败'))
  } finally {
    loading.value = false
  }
}

function onSearch() {
  fetchData()
}

function onReset() {
  keyword.value = ''
  wcTypeFilter.value = ''
  conditions.value = []
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

const saving = ref(false)

async function handleSave() {
  // 提交中不重复受理（UE-P0-05）：按钮已 loading，这里再兜一道
  if (saving.value) return
  saving.value = true
  try {
    const data = { ...editing.value }
    if (isEdit.value) {
      await put(`/work-centers/${data.id}`, data)
      showToast('工作中心更新成功')
    } else {
      await post('/work-centers', data)
      showToast('工作中心创建成功')
    }
    showDialog_.value = false
    page.value = 1
    fetchData()
  } catch (e: any) {
    showToast(errorText(e, '操作失败'))
  } finally {
    saving.value = false
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
        await del(`/work-centers/${item.id}`)
        showToast('删除成功')
        page.value = 1
        fetchData()
      } catch (e: any) {
        showToast(errorText(e, '删除失败'))
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
  <div class="ziwi-page">
    <!-- 搜索栏：条件 → 输入 → 提交 → 清空 → 查询延伸 | 创建靠右 -->
    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索工作中心编码/名称"
      :loading="loading"
      class="ziwi-mb-4"
      @search="onSearch"
      @reset="onReset"
      @advanced="showSearch = true"
    >
      <template #filters>
        <div class="ziwi-w-40">
          <SelectField v-model="wcTypeFilter" :options="WC_TYPE_OPTIONS" placeholder="工作中心类型" clearable />
        </div>
      </template>
      <template #actions>
        <van-button type="success" @click="openCreate">新增工作中心</van-button>
      </template>
    </ZiwiListToolbar>

    <!-- 高级检索条件 chips -->
    <div v-if="conditions.length" class="ziwi-flex ziwi-flex-wrap ziwi-gap-2 ziwi-mb-3 ziwi-px-1">
      <van-tag
        v-for="c in conditions"
        :key="c.uid"
        type="primary"
        closeable
        size="medium"
        @close="removeCondition(c.uid)"
      >{{ condText(c) }}</van-tag>
      <van-button size="mini" plain type="primary" @click="onResetSubmit">清空</van-button>
    </div>

    <!-- 列表 -->
    <ZiwiStateView v-if="loading" state="loading" skeleton="rows" :skeleton-count="5" />
    <ZiwiStateView
      v-else-if="list.length === 0"
      :state="isEmptyFiltered ? 'empty-filtered' : 'empty-true'"
      object-name="工作中心"
      :conditions="activeFilterTexts"
      primary-text="新增工作中心"
      @create="openCreate"
      @clear-filter="onReset"
    />
    <div v-else class="wc-table-wrap ziwi-table-scroll">
      <table class="wc-table">
        <thead>
          <tr>
            <th>工作中心编码</th>
            <th>工作中心名称</th>
            <th>类型</th>
            <th class="num">效率</th>
            <th class="num">设备数</th>
            <th class="num">人员数</th>
            <th>ESD</th>
            <th>状态</th>
            <th class="op">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="item in list" :key="item.id">
            <tr @click="toggleExpand(item.id)">
              <td>{{ item.code }}</td>
              <td>{{ item.name }}</td>
              <td>
                <van-tag type="primary" size="small">{{ getWcTypeLabel(item.wc_type) }}</van-tag>
              </td>
              <td class="num">{{ (item.efficiency * 100).toFixed(0) }}%</td>
              <td class="num">{{ item.equipment_count }}</td>
              <td class="num">{{ item.labor_count }}</td>
              <td>
                <van-tag v-if="item.is_esd" type="warning" size="small">是</van-tag>
                <span v-else class="ziwi-text-muted">—</span>
              </td>
              <td>
                <van-tag v-if="item.is_active" type="success" size="small">启用</van-tag>
                <van-tag v-else type="default" size="small">禁用</van-tag>
              </td>
              <td class="op">
                <!-- 行内操作已结构性消掉：这里只留一个**不可点**的展开指示箭头。
                     原来这里是三个 size="mini" 图标键（展开/编辑/删除），实测 22×24，
                     远低于 --ziwi-touch-min(48)，而且在油污手套下三个相邻小键极易误触。
                     其中"展开"键本身就是重复的 —— 整行已经绑了 toggleExpand。
                     编辑/删除移入展开区的 .row-actions，那里有地方给到 48。
                     箭头保持不可点，是为了不丢掉"这行能展开"的可见提示。 -->
                <van-icon
                  :name="expandedId === item.id ? 'arrow-up' : 'arrow-down'"
                  class="ziwi-row-chevron"
                  aria-hidden="true"
                />
              </td>
            </tr>
            <tr v-if="expandedId === item.id" class="row-detail-row">
              <td :colspan="9">
                <ListRowDetail :item="item" :fields="cfg.rowDetailFields" />
                <div class="ziwi-row-actions">
                  <van-button type="primary" plain icon="edit" @click.stop="openEdit(item)">编辑</van-button>
                  <van-button type="danger" plain icon="delete" @click.stop="handleDelete(item)">删除</van-button>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- 创建/编辑弹窗 -->
    <ZiwiFormSheet
      v-model:show="showDialog_"
      :title="isEdit ? '编辑工作中心' : '新增工作中心'"
      :submitting="saving"
      submit-text="保存"
      @submit="handleSave"
    >
      <div class="ziwi-stack-3">
        <van-field v-model="editing.code" label="工作中心编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="工作中心名称" required placeholder="请输入名称" />
        <van-field label="工作中心类型" required>
          <template #input>
            <SelectField v-model="editing.wc_type" :options="WC_TYPE_OPTIONS" class="ziwi-w-full" />
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
    </ZiwiFormSheet>

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>

<style scoped>
.wc-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.wc-table {
  width: 100%;
  min-width: 920px;
  border-collapse: collapse;
  font-size: 14px;
  color: var(--ziwi-text-primary, #1e293b);
  background: var(--ziwi-bg, #fff);
}

.wc-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--ziwi-bg-elevated, #f5f7fa);
  text-align: left;
  padding: 10px 12px;
  font-weight: 600;
  white-space: nowrap;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  color: var(--ziwi-text-primary, #1e293b);
}

.wc-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  text-align: left;
  vertical-align: middle;
  color: var(--ziwi-text-primary, #1e293b);
}

.wc-table tbody td.num {
  text-align: right;
  white-space: nowrap;
}

.wc-table tbody td.op {
  text-align: right;
  white-space: nowrap;
}

/* 展开指示箭头与展开区操作条走共享类 .ziwi-row-chevron / .ziwi-row-actions
   （定义在 styles/ziwi-utilities.css —— 4 个基础资料页都要用，写 scoped 就是复制 4 遍）。 */

/* 数据行本身是"点行展开"的点击目标，必须 ≥ --ziwi-touch-min。
   ★ 别小看这一条：把行内三个图标键拿走后，行高从 46 掉到 40（H 档 34）——
     原来是那几个 24px 的 mini 按钮在"撑"行高。点击目标变小等于换了个方式不达标。 */
.wc-table tbody tr:not(.row-detail-row) {
  height: var(--ziwi-touch-min);
}

/* 行展开（并集详情）整行底色弱化，凸显多列并排明细 */
.wc-table tbody tr.row-detail-row td {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.02));
  padding: 0;
  /* B-15：同 ProductList —— colspan 单元格要能收缩，明细区才会内部横滚。 */
  max-width: 0;
}

.wc-table tbody tr:hover:not(.row-detail-row) {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.04));
}

@media (max-width: 768px) {
  .wc-table {
    font-size: 13px;
  }
  .wc-table thead th,
  .wc-table tbody td {
    padding: 8px 10px;
  }
}
</style>
