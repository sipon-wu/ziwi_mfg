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
import { OP_TYPE_OPTIONS, opTypeLabel, CLEAN_LEVEL_OPTIONS, cleanLevelLabel } from '@/config/enums'
import type { SearchCondition } from '@/types/search'

/** 环境要求（环）。后端真源 app/schemas/basic_data.py::EnvReq，存储为 JSON 文本。 */
interface EnvReq {
  clean_level: string | null
  temp_min: number | null
  temp_max: number | null
  humidity_min: number | null
  humidity_max: number | null
  /** 旧自由文本的暂存位：解析不了的旧数据会落到这里，保存时原样带回，不静默丢。 */
  legacy_text?: string | null
}

/**
 * 表单态。有意与 `EnvReq` 分开：Vant 的 van-field `v-model` 只收
 * `string | number | undefined`，绑 `number | null` 直接 TS2322；
 * 空输入时 `.number` 修饰符又给出 `''` 而不是 null。
 * 所以表单里用 `''` 表示"没填"，提交前由 `cleanEnv()` 统一转回 null。
 */
interface EnvForm {
  clean_level: string
  temp_min: number | string
  temp_max: number | string
  humidity_min: number | string
  humidity_max: number | string
  legacy_text?: string | null
}

interface Operation {
  id: number
  code: string
  name: string
  op_type: string
  setup_time: number
  unit_time: number
  /** 同装量(件/批)：一次加工同时处理几件。默认 1 = 单件流。
   *  setup_time/unit_time 记的都是**每批**时长，每件占机 = (两者之和)/batch_size。 */
  batch_size: number
  labor_cert: string | null
  equip_req: string | null
  material_reqs: string | null
  sop_refs: string | null
  /** 结构化环境要求（温度/湿度/洁净度）。此前是自由文本且无输入框 → 全库 0 条有值。 */
  env_req: EnvReq | null
  /** env_req.clean_level 的派生平铺值（后端读取时现算，不落库），供检索/列直取。 */
  clean_level: string | null
  remark: string | null
  is_active: boolean
  // 关键工序：PFMEA 发布时按 fmea_hierarchies.operation_id 自动置真，
  // 也可在这里手工开关（手工置真不会被发布流程清掉 —— 发布只置真、不清零）。
  is_critical: boolean
  created_at: string
}

// 工序类型候选项统一来自 @/config/enums（后端真源 core/enums.py）。
// 原来这里自存一份 11 项常量，漏了 incoming_qc/process_qc/final_qc ——
// 库里真有这三个值，于是列表直接印英文原文。
const rawList = ref<Operation[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const opTypeFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<Operation>>({})
const isEdit = ref(false)

/** 空环境要求。用独立 ref 而不是 editing.env_req：editing 是 Partial，
 *  env_req 可能为 null，模板里 `editing.env_req.temp_min` 会踩空。 */
function emptyEnv(): EnvForm {
  return {
    clean_level: '',
    temp_min: '',
    temp_max: '',
    humidity_min: '',
    humidity_max: '',
    legacy_text: null,
  }
}

/** 接口值 → 表单值。null 统一落成 `''`，别把 null 绑进 van-field。 */
function toEnvForm(e: EnvReq | null): EnvForm {
  if (!e) return emptyEnv()
  return {
    clean_level: e.clean_level || '',
    temp_min: e.temp_min ?? '',
    temp_max: e.temp_max ?? '',
    humidity_min: e.humidity_min ?? '',
    humidity_max: e.humidity_max ?? '',
    legacy_text: e.legacy_text ?? null,
  }
}

const envForm = ref<EnvForm>(emptyEnv())

/** 表单里的「每件占机」试算：同装量 >1 时让填表的人当场看到摊算结果，
 *  否则很容易把一炉的 120 分当成一件的时长填进去 —— 那正是这条线被低估 4 倍的来路。 */
const perPiece = computed<number | null>(() => {
  const batch = Math.max(1, Number(editing.value.batch_size) || 1)
  const total = (Number(editing.value.unit_time) || 0) + (Number(editing.value.setup_time) || 0)
  if (total <= 0) return null
  return Math.round((total / batch) * 100) / 100
})

/** 表单值 → 提交值：空的数值不留 `''`（后端会收到字符串，float 校验直接 422）。 */
function cleanEnv(v: EnvForm): EnvReq | null {
  const out: Record<string, any> = {}
  if (v.clean_level) out.clean_level = v.clean_level
  for (const k of ['temp_min', 'temp_max', 'humidity_min', 'humidity_max'] as const) {
    const n = v[k]
    if (n === null || n === undefined || n === '') continue
    const num = Number(n)
    if (Number.isFinite(num)) out[k] = num
  }
  if (v.legacy_text) out.legacy_text = v.legacy_text
  return Object.keys(out).length ? (out as EnvReq) : null
}

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
    batch_size: 1,
    labor_cert: null,
    equip_req: null,
    material_reqs: null,
    sop_refs: null,
    env_req: null,
    remark: null,
    is_active: true,
    is_critical: false,
  }
  envForm.value = emptyEnv()
  showDialog_.value = true
}

function openEdit(item: Operation) {
  isEdit.value = true
  editing.value = { ...item }
  envForm.value = toEnvForm(item.env_req)
  showDialog_.value = true
}

/** 环境要求的前置校验。后端也会拦（EnvReq model_validator），
 *  这里先拦一次是为了给一句人话，而不是让 422 的英文 detail 直接弹给车间。 */
function checkEnvRange(v: EnvReq | null): string {
  if (!v) return ''
  if (v.temp_min != null && v.temp_max != null && Number(v.temp_min) > Number(v.temp_max)) {
    return '温度下限不能大于上限'
  }
  if (v.humidity_min != null && v.humidity_max != null && Number(v.humidity_min) > Number(v.humidity_max)) {
    return '湿度下限不能大于上限'
  }
  const pairs: Array<[keyof EnvReq, string]> = [
    ['humidity_min', '湿度下限'],
    ['humidity_max', '湿度上限'],
  ]
  for (const [k, label] of pairs) {
    const n = v[k]
    if (n == null) continue
    if (!(Number(n) >= 0 && Number(n) <= 100)) return `${label}要填 0~100 的百分数`
  }
  return ''
}

const saving = ref(false)

async function handleSave() {
  // 提交中不重复受理（UE-P0-05）：按钮已 loading，这里再兜一道
  if (saving.value) return
  const env = cleanEnv(envForm.value)
  const envErr = checkEnvRange(env)
  if (envErr) {
    showToast(envErr)
    return
  }
  saving.value = true
  try {
    const data = { ...editing.value, env_req: env }
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
  // 未知值显示「未知（原文）」而不是原文：兜底回显会让脏数据看起来像正常值，
  // `mfg_demo` 里 65 条 op_type=production 就是这么藏了三轮没人发现。
  return opTypeLabel(v)
}

onMounted(() => {
  fetchData()
  fetchGroups()
})

// ══════════════ 报工小组（C-107）══════════════
//
// 为什么挂在工序管理页里而不是独立菜单：小组是"把工序编成组"，
// 和工序是同一件事的两面。分成两个菜单后，改完工序还得再找一个页面
// 去勾组，而那个页面上又列一遍全部工序 —— 两处看到的工序池会不一致。
//
// ★ 勾选池直接用本页已加载的 `rawList`（page_size=100）。不单独再拉一份：
//   两份列表在"刚新建完一道工序还没刷新"时会不一致，勾出来的组会缺工序。

interface OperationGroup {
  id: number
  code: string
  name: string
  remark: string | null
  is_active: boolean
  operation_count: number
}

/** 0 = 工序 / 1 = 报工小组。用数字而不是字符串，与 van-tabs 的 v-model 口径一致。 */
const tab = ref(0)
const groups = ref<OperationGroup[]>([])
const groupsLoading = ref(false)
const groupKeyword = ref('')
const showGroupSheet = ref(false)
const groupIsEdit = ref(false)
const groupSaving = ref(false)
/** 正在编辑的组。字段一律用**非空**类型（`''` 表示没填），
 *  因为 Vant 的 `van-field` 只收 `string | number | undefined`，
 *  绑 `string | null | undefined` 直接 TS2322 —— 与本页 envForm 同一处理。 */
interface GroupForm {
  id: number
  code: string
  name: string
  remark: string
  is_active: boolean
}
/** `id === 0` 即新建。用 id 判而不是另开一个 boolean：两个状态源迟早对不上。 */
const groupForm = ref<GroupForm>({ id: 0, code: '', name: '', remark: '', is_active: true })
/** 勾选中的工序 id。**必须与 editingGroup 分开**：它只在保存时一次性提交，
 *  中途取消不该污染列表里那一行的 operation_count。 */
const groupOpIds = ref<number[]>([])

const filteredGroups = computed<OperationGroup[]>(() => {
  const kw = groupKeyword.value.trim().toLowerCase()
  if (!kw) return groups.value
  return groups.value.filter(
    (g) =>
      (g.code || '').toLowerCase().includes(kw) ||
      (g.name || '').toLowerCase().includes(kw),
  )
})

async function fetchGroups() {
  groupsLoading.value = true
  try {
    const res = await get<{ items?: OperationGroup[] }>('/operation-groups', {
      params: { page: 1, page_size: 100 },
    })
    groups.value = res.items || []
  } catch (e: any) {
    showToast(errorText(e, '获取报工小组失败'))
  } finally {
    groupsLoading.value = false
  }
}

function openGroupCreate() {
  groupIsEdit.value = false
  groupForm.value = { id: 0, code: '', name: '', remark: '', is_active: true }
  groupOpIds.value = []
  showGroupSheet.value = true
}

async function openGroupEdit(g: OperationGroup) {
  groupIsEdit.value = true
  // ★ 列表行里没有 operation_ids（列表只带计数），必须读详情回填。
  //   拿列表行直接开编辑框会让"保存"把成员覆盖成空 —— 界面看起来正常，
  //   那几道工序的人从此看不见这批活。
  try {
    const d = await get<OperationGroup & { operation_ids?: number[] }>(
      `/operation-groups/${g.id}`,
    )
    groupForm.value = {
      id: d.id,
      code: d.code || '',
      name: d.name || '',
      remark: d.remark || '',
      is_active: d.is_active !== false,
    }
    groupOpIds.value = [...(d.operation_ids || [])]
    showGroupSheet.value = true
  } catch (e: any) {
    showToast(errorText(e, '读取小组详情失败'))
  }
}

async function saveGroup() {
  const code = groupForm.value.code.trim()
  const name = groupForm.value.name.trim()
  if (!code || !name) {
    showToast('小组编码与名称都要填')
    return
  }
  groupSaving.value = true
  try {
    const payload: Record<string, any> = {
      code,
      name,
      remark: groupForm.value.remark || null,
      is_active: groupForm.value.is_active,
      // ★ 显式带上（可能是 []）：这是"覆盖写入"。想只改名就传 undefined，
      //   而本页没有"只改名"的场景，一律整体保存。
      operation_ids: groupOpIds.value,
    }
    if (groupForm.value.id > 0) {
      await put(`/operation-groups/${groupForm.value.id}`, payload)
      showToast('已保存')
    } else {
      await post('/operation-groups', payload)
      showToast('已创建')
    }
    showGroupSheet.value = false
    fetchGroups()
  } catch (e: any) {
    showToast(errorText(e, '保存失败'))
  } finally {
    groupSaving.value = false
  }
}

function removeGroup(g: OperationGroup) {
  showDialog({
    title: '确认删除',
    message: `确定删除报工小组「${g.name}」？组内 ${g.operation_count} 道工序的归属会一起清除（工序本身不受影响）。`,
    showCancelButton: true,
  }).then(async (action) => {
    // ★ 这里**不写** `(action: string)`：`showDialog().then` 的参数类型是
    //   `DialogAction | undefined`，写窄成 `string` 就与回调签名不符（TS2345）。
    //   本页上面两处旧代码就是那么写的，一直在错误清单里躺着 —— 新代码不再加一份。
    if (action !== 'confirm') return
    try {
      await del(`/operation-groups/${g.id}`)
      showToast('删除成功')
      fetchGroups()
    } catch (e: any) {
      showToast(errorText(e, '删除失败'))
    }
  })
}

/** 勾选/取消一道工序。用数组而不是 Set：van-checkbox-group 要数组。 */
function toggleGroupOp(id: number) {
  const i = groupOpIds.value.indexOf(id)
  if (i >= 0) groupOpIds.value.splice(i, 1)
  else groupOpIds.value.push(id)
}
</script>

<template>
  <div class="ziwi-page">
    <!-- 两个 tab：工序本体 / 报工小组。小组是「把工序编成组」，
         和工序是同一件事的两面，分成两个菜单会让两处各列一份工序池。 -->
    <van-tabs v-model:active="tab" class="op-tabs">
      <van-tab title="工序"></van-tab>
      <van-tab title="报工小组"></van-tab>
    </van-tabs>

    <template v-if="tab === 0">
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
            <th>洁净度</th>
            <th>关键</th>
            <th class="num">准备时间(min/批)</th>
            <th class="num">加工时间(min/批)</th>
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
              <td>
                <!-- 洁净度：无尘车间排产第一眼要看的字段。空值给「—」而不是留白，
                     否则看起来像漏渲染；`cleanLevelLabel` 对未知值显「未知（原文）」。 -->
                <van-tag v-if="item.clean_level" type="warning" plain class="op-clean">
                  {{ cleanLevelLabel(item.clean_level) }}
                </van-tag>
                <span v-else class="op-dash">—</span>
              </td>
              <td>
                <van-tag v-if="item.is_critical" type="danger">关键</van-tag>
                <span v-else class="op-dash">—</span>
              </td>
              <td class="num">{{ item.setup_time }}</td>
              <td class="num">
                {{ item.unit_time }}
                <!-- 同装量 >1 时把摊算写成 120÷4，否则单看 120 会以为是一件的时长 -->
                <span v-if="item.batch_size > 1" class="op-batch">÷{{ item.batch_size }}</span>
              </td>
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
    </template>

    <!-- ══════════ 报工小组 ══════════ -->
    <template v-else>
      <div class="op-group-bar">
        <van-search
          v-model="groupKeyword"
          placeholder="搜索小组编码/名称"
          class="op-group-search"
        />
        <van-button type="success" size="small" @click="openGroupCreate">新增小组</van-button>
      </div>

      <ZiwiStateView v-if="groupsLoading" state="loading" skeleton="rows" :skeleton-count="3" />
      <ZiwiStateView
        v-else-if="filteredGroups.length === 0"
        :state="groupKeyword ? 'empty-filtered' : 'empty-true'"
        object-name="报工小组"
        :conditions="groupKeyword ? [`关键词「${groupKeyword}」`] : []"
        primary-text="新增小组"
        @create="openGroupCreate"
        @clear-filter="groupKeyword = ''"
      />
      <van-cell-group v-else inset>
        <van-cell
          v-for="g in filteredGroups"
          :key="g.id"
          :title="g.name"
          :label="`${g.code} · ${g.operation_count} 道工序` + (g.is_active ? '' : ' · 已停用')"
          is-link
          @click="openGroupEdit(g)"
        >
          <template #right-icon>
            <van-button
              size="mini" plain type="danger"
              @click.stop="removeGroup(g)"
            >删除</van-button>
          </template>
        </van-cell>
      </van-cell-group>
    </template>

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
        <van-field v-model.number="editing.setup_time" label="准备时间(min/批)" type="number" placeholder="0" />
        <van-field v-model.number="editing.unit_time" label="加工时间(min/批)" type="number" placeholder="0" />
        <!-- 同装量（件/批）。炉/烘箱/罐这类工序的工艺时间是**一炉**的，不是一件的：
             固化烘烤 120 分/炉、一炉 4 个 → 这里填 4，不要手算成 30 再填上面那格。
             手算的坏处是"4"这个事实从库里消失，跟工艺卡对不上账。 -->
        <van-field v-model.number="editing.batch_size" label="同装量(件/批)" type="number" placeholder="1" />
        <div class="op-env-hint" style="padding: 0 var(--ziwi-space-4) var(--ziwi-space-2)">
          每件占机 = (加工 + 准备) ÷ 同装量
          <template v-if="perPiece != null"> ≈ <b>{{ perPiece }}</b> 分/件</template>
          <template v-else>；单件流填 1</template>
        </div>

        <!-- 环境要求（环）：温度 / 湿度 / 洁净度。设计文档早就定义了这个字段
             （docs/basic-data-code-plan.md:66），但一直只有类型声明、没有输入框，
             于是全库 233 条工序 0 条有值、Tab7「环」是纸面。 -->
        <div class="op-form-section">
          <div class="op-form-section-title">环境要求（环）</div>
          <van-field label="洁净度等级">
            <template #input>
              <SelectField
                v-model="envForm.clean_level"
                :options="CLEAN_LEVEL_OPTIONS"
                placeholder="未评估"
                class="ziwi-w-full"
              />
            </template>
          </van-field>
          <div class="op-env-pair">
            <van-field v-model.number="envForm.temp_min" type="number" label="温度下限" placeholder="—" />
            <van-field v-model.number="envForm.temp_max" type="number" label="温度上限" placeholder="—" />
          </div>
          <div class="op-env-pair">
            <van-field v-model.number="envForm.humidity_min" type="number" label="湿度下限" placeholder="—" />
            <van-field v-model.number="envForm.humidity_max" type="number" label="湿度上限" placeholder="—" />
          </div>
          <div class="op-env-hint">
            温度单位 ℃、湿度单位 %RH（填 0~100 的百分数）。只填能确定的，留空表示未规定；「无洁净要求」是明确结论，和留空不是一回事。
          </div>
          <div v-if="envForm.legacy_text" class="op-env-legacy">
            <span>旧自由文本：{{ envForm.legacy_text }}（不参与排产/外协判定，请按上面字段重填）</span>
            <van-button size="mini" plain type="primary" @click="envForm.legacy_text = null">清除</van-button>
          </div>
        </div>

        <van-field label="关键工序">
          <template #input>
            <van-switch v-model="editing.is_critical" />
          </template>
        </van-field>
        <div class="op-critical-hint">
          PFMEA 发布时，被标记为高风险（且关联了本工序）的结构树节点会自动把这里置为开；
          自动标记只增不清，降风险后需在此手工关闭。
        </div>
        <van-field v-model="editing.remark" label="备注" type="textarea" rows="2" placeholder="可选" />
      </div>
    </ZiwiFormSheet>

    <!-- 报工小组 编辑弹窗 -->
    <van-popup
      v-model:show="showGroupSheet"
      position="bottom"
      round
      class="op-group-popup"
      teleport="body"
    >
      <div class="op-group-sheet">
        <div class="op-group-sheet-head">
          <span>{{ groupIsEdit ? '编辑报工小组' : '新增报工小组' }}</span>
        </div>

        <div class="op-group-sheet-body">
          <van-field v-model="groupForm.code" label="小组编码" placeholder="如 G-FRONT" />
          <van-field v-model="groupForm.name" label="小组名称" placeholder="如 前段组" />
          <van-field v-model="groupForm.remark" label="备注" placeholder="选填" />
          <van-cell title="启用" center>
            <template #right-icon>
              <van-switch v-model="groupForm.is_active" size="20" />
            </template>
          </van-cell>

          <div class="op-group-pick-title">
            组内工序（已选 {{ groupOpIds.length }} 道）
          </div>
          <!-- 勾选池直接用本页已加载的工序列表：另拉一份会出现
               「刚建的工序还没刷新」，勾出来的组缺工序。 -->
          <div class="op-group-pick">
            <button
              v-for="o in rawList"
              :key="o.id"
              type="button"
              class="op-group-chip"
              :class="{ on: groupOpIds.includes(o.id) }"
              @click="toggleGroupOp(o.id)"
            >{{ o.name }}</button>
            <span v-if="rawList.length === 0" class="op-group-hint">
              还没有工序，先到「工序」页签新建
            </span>
          </div>
        </div>

        <div class="op-group-sheet-foot">
          <van-button block plain @click="showGroupSheet = false">取消</van-button>
          <van-button block type="primary" :loading="groupSaving" @click="saveGroup">
            保存
          </van-button>
        </div>
      </div>
    </van-popup>

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
  /* 9 列（多了「洁净度」）。窄于此值就整体横滚，不压缩列宽 ——
     压到 840 会出现「十万级（ISO 8）」折成三行。 */
  min-width: 940px;
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

/* 「关键」列的空值占位：不留白，避免看起来像漏渲染 */
.op-dash {
  color: var(--ziwi-text-tertiary, #94a3b8);
}

/* 关键工序开关的说明文案。放在表单里而不是 tooltip —— 移动端 tooltip 点不到。 */
.op-critical-hint {
  padding: 0 16px 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ziwi-text-secondary, #64748b);
}

/* 洁净度列：Vant4 的 Tag 没有 size="small"，靠字号压到与相邻 tag 同高
   （加 size 会触发 TS2322，vue-tsc 错误数只许不增）。 */
.op-clean {
  padding: 0 4px;
  font-size: 11px;
  line-height: 16px;
}

/* 同装量标注「÷4」：让"120 是一炉的量"在列表里就能看出来，
   而不是让人以为这件活单件要 120 分钟。 */
.op-batch {
  margin-left: 2px;
  color: var(--ziwi-primary);
  font-size: 11px;
}

/* 表单里的分组区块：环境要求是独立一"环"，跟上面的工时字段不是一类东西，
   加一条分隔线，避免看成"又两个数字输入框"。 */
.op-form-section {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid var(--ziwi-border, #ebedf0);
}

.op-form-section-title {
  padding: 8px 16px 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ziwi-text-primary, #1e293b);
}

/* 温湿度上下限成对录入：宽屏两列、窄屏单列。
   用 grid 而不是 flex，是为了让两个 van-field 的 label 宽度自动对齐。 */
.op-env-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
}

/* ★ 断点取 UE §4.2 分档真源（600 / 768 / 1024），不写自造值。
   原来这里写 `max-width: 480px` —— 480 不在允许集里，会让全站断点碎片化：
   同一套栅格在 481~600 之间按两列排，而那时正是窄屏最容易挤爆的区间。
   抬到 600 后与「手机 / 平板」分界一致，且方向上只提前收成一列（不会溢出）。 */
@media (max-width: 600px) {
  .op-env-pair {
    grid-template-columns: 1fr;
  }
}

.op-env-hint,
.op-env-legacy {
  padding: 0 16px 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ziwi-text-secondary, #64748b);
}

.op-env-legacy {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ziwi-text-tertiary, #94a3b8);
}

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

.op-tabs {
  margin-bottom: 12px;
}

.op-group-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.op-group-search {
  flex: 1;
  padding: 0;
}

/* 弹层占屏 78%：留出顶部让用户还能看见底下的工序表，
   确认自己改的是哪一条。高度写在 class 里而不是内联
   —— UI 契约闸 A 项 ratchet 只许降不许升。 */
.op-group-popup {
  height: 78%;
}

.op-group-sheet {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.op-group-sheet-head {
  padding: 14px 16px;
  font-weight: 600;
  font-size: 16px;
  border-bottom: 1px solid var(--ziwi-border, #e5e7eb);
}

.op-group-sheet-body {
  flex: 1;
  overflow-y: auto;
  padding-bottom: 8px;
}

.op-group-pick-title {
  padding: 12px 16px 6px;
  font-size: 13px;
  color: var(--ziwi-text-secondary, #64748b);
}

.op-group-pick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 16px 12px;
}

/* 勾选片：热区 44 起步（车间手势操作），选中态靠背景+边框双写，
   不只靠颜色 —— 产线屏色偏时只变颜色等于没变。 */
.op-group-chip {
  min-height: 44px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid var(--ziwi-border, #e5e7eb);
  background: var(--ziwi-bg-card, #fff);
  color: var(--ziwi-text-primary, #1e293b);
  font-size: 14px;
}

.op-group-chip.on {
  border-color: var(--van-primary-color, #1989fa);
  background: rgba(25, 137, 250, 0.1);
  font-weight: 600;
}

.op-group-hint {
  font-size: 13px;
  color: var(--ziwi-text-secondary, #64748b);
}

.op-group-sheet-foot {
  display: flex;
  gap: 10px;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--ziwi-border, #e5e7eb);
}
</style>
