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

const rawList = ref<Operation[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const opTypeFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<Operation>>({})
const isEdit = ref(false)

// 高级检索 + 行展开（并集方式多列并排）
const cfg = getSearchConfig('operations')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<Operation>(cfg)
const list = computed<Operation[]>(() =>
  conditions.value.length ? applyFilter(rawList.value) : rawList.value,
)
/* 空态必须区分两类（UE-12）：条件没命中 vs 本来就没有。
   混成一句「暂无数据」会让用户以为数据丢了，也不知道下一步该清条件还是该新建。 */
const activeFilterTexts = computed<string[]>(() => {
  const out: string[] = []
  if (keyword.value) out.push(`关键词「${keyword.value}」`)
  if (opTypeFilter.value) {
    const hit = OP_TYPE_OPTIONS.find((o) => o.value === opTypeFilter.value)
    out.push(`类型「${hit?.label ?? opTypeFilter.value}」`)
  }
  conditions.value.forEach((c) => out.push(condText(c)))
  return out
})
const isEmptyFiltered = computed(() => activeFilterTexts.value.length > 0)
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

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: 1, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (opTypeFilter.value) params.op_type = opTypeFilter.value
    const res = await get('/operations', { params })
    rawList.value = res.items || []
  } catch (e: any) {
    showToast(errorText(e, '获取工序列表失败'))
  } finally {
    loading.value = false
  }
}

function onSearch() {
  fetchData()
}

function onReset() {
  keyword.value = ''
  opTypeFilter.value = ''
  conditions.value = []
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

const saving = ref(false)

async function handleSave() {
  // 提交中不重复受理（UE-P0-05）：按钮已 loading，这里再兜一道
  if (saving.value) return
  saving.value = true
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
    showToast(errorText(e, '操作失败'))
  } finally {
    saving.value = false
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
        showToast(errorText(e, '删除失败'))
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
  <div class="ziwi-page">
    <!-- 搜索栏：条件 → 输入 → 提交 → 清空 → 查询延伸 | 创建靠右 -->
    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索工序编码/名称"
      :loading="loading"
      class="ziwi-mb-4"
      @search="onSearch"
      @reset="onReset"
      @advanced="showSearch = true"
    >
      <template #filters>
        <div class="ziwi-w-40">
          <SelectField v-model="opTypeFilter" :options="OP_TYPE_OPTIONS" placeholder="工序类型" clearable />
        </div>
      </template>
      <template #actions>
        <van-button type="success" @click="openCreate">新增工序</van-button>
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
    <ZiwiStateView
      v-if="loading"
      state="loading"
      skeleton="rows"
      :skeleton-count="5"
    />
    <ZiwiStateView
      v-else-if="list.length === 0"
      :state="isEmptyFiltered ? 'empty-filtered' : 'empty-true'"
      object-name="工序"
      :conditions="activeFilterTexts"
      primary-text="新增工序"
      @create="openCreate"
      @clear-filter="onReset"
    />
    <div v-else class="op-table-wrap ziwi-table-scroll">
      <table class="op-table">
        <thead>
          <tr>
            <th>工序编码</th>
            <th>工序名称</th>
            <th>工序类型</th>
            <th class="num">准备时间(min)</th>
            <th class="num">单件时间(min/件)</th>
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
                <van-tag type="primary" size="small">{{ getOpTypeLabel(item.op_type) }}</van-tag>
              </td>
              <td class="num">{{ item.setup_time }}</td>
              <td class="num">{{ item.unit_time }}</td>
              <td>
                <van-tag v-if="item.is_active" type="success" size="small">启用</van-tag>
                <van-tag v-else type="default" size="small">禁用</van-tag>
              </td>
              <td class="op">
                <!-- 行内操作结构性消掉，同 WorkCenterList：只留不可点的展开指示，
                     编辑/删除移入展开区（那里能给到 48 的热区）。 -->
                <van-icon
                  :name="expandedId === item.id ? 'arrow-up' : 'arrow-down'"
                  class="ziwi-row-chevron"
                  aria-hidden="true"
                />
              </td>
            </tr>
            <tr v-if="expandedId === item.id" class="row-detail-row">
              <td :colspan="7">
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
      :title="isEdit ? '编辑工序' : '新增工序'"
      :submitting="saving"
      submit-text="保存"
      @submit="handleSave"
    >
      <div class="ziwi-stack-3">
        <van-field v-model="editing.code" label="工序编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="工序名称" required placeholder="请输入名称" />
        <van-field label="工序类型" required>
          <template #input>
            <SelectField v-model="editing.op_type" :options="OP_TYPE_OPTIONS" class="ziwi-w-full" />
          </template>
        </van-field>
        <van-field v-model.number="editing.setup_time" label="准备时间(min)" type="number" placeholder="0" />
        <van-field v-model.number="editing.unit_time" label="单件时间(min/件)" type="number" placeholder="0" />
        <van-field v-model="editing.remark" label="备注" type="textarea" rows="2" placeholder="可选" />
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
.op-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.op-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
  font-size: 14px;
  color: var(--ziwi-text-primary, #1e293b);
  background: var(--ziwi-bg, #fff);
}

.op-table thead th {
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

.op-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  text-align: left;
  vertical-align: middle;
  color: var(--ziwi-text-primary, #1e293b);
}

.op-table tbody td.num {
  text-align: right;
  white-space: nowrap;
}

.op-table tbody td.op {
  text-align: right;
  white-space: nowrap;
}

/* .op-btns 已随行内操作移入展开区删除（改用共享类 .ziwi-row-actions）。 */

/* 行展开（并集详情）整行底色弱化，凸显多列并排明细 */
/* 数据行本身是"点行展开"的点击目标，必须 ≥ --ziwi-touch-min（同 WorkCenterList：
   拿走行内图标键后行高会从 46 掉到 40，原来是 mini 按钮在撑行高）。 */
.op-table tbody tr:not(.row-detail-row) {
  height: var(--ziwi-touch-min);
}

.op-table tbody tr.row-detail-row td {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.02));
  padding: 0;
  /* B-15：同 ProductList —— colspan 单元格要能收缩，明细区才会内部横滚，
     否则末几列被表格祖先裁掉且滚不到。 */
  max-width: 0;
}

.op-table tbody tr:hover:not(.row-detail-row) {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.04));
}

@media (max-width: 768px) {
  .op-table {
    font-size: 13px;
  }
  .op-table thead th,
  .op-table tbody td {
    padding: 8px 10px;
  }
}
</style>
