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

interface Product {
  id: number
  code: string
  name: string
  spec: string | null
  unit: string
  product_type: string
  category: string | null
  weight: number | null
  drawing_url: string | null
  is_active: boolean
  remark: string | null
  created_at: string
}

const PRODUCT_TYPE_OPTIONS = [
  { value: 'final', label: '成品' },
  { value: 'semi', label: '半成品' },
  { value: 'raw', label: '原材料' },
]

const rawList = ref<Product[]>([])
const page = ref(1)
const pageSize = 100
const loading = ref(false)
const keyword = ref('')
const typeFilter = ref('')
const categoryFilter = ref('')
const showDialog_ = ref(false)
const editing = ref<Partial<Product>>({})
const isEdit = ref(false)

// 高级检索 + 行展开（并集方式多列并排）
const cfg = getSearchConfig('products')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<Product>(cfg)
const list = computed<Product[]>(() =>
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

/* ── 产品默认工艺路线 ──────────────────────────────────────────
 * 这张关联表此前零 API、零入口。没有默认路线的产品，建工单时
 * route_id 永远是 NULL → 报工每条都被判成"完工" → 完工口径与
 * 工序流转量恒等，双口径静默退化成单口径。
 * 所以这个入口不是"锦上添花"，是上面那条断链的维护点。
 * ──────────────────────────────────────────────────────────── */
interface RouteLink {
  id: number
  route_id: number
  is_default: boolean
  effective_from: string | null
  effective_to: string | null
  route_code: string | null
  route_name: string | null
  route_version: number | null
  route_status: string | null
  step_count: number | null
  effective_now?: boolean
}

const showRouteSheet = ref(false)
const routeProduct = ref<Product | null>(null)
const routeLinks = ref<RouteLink[]>([])
const routeHasEffectiveDefault = ref(false)
const routeLoading = ref(false)
const allRoutes = ref<Array<{ id: number; code: string; name: string; version: number }>>([])
const newRouteId = ref<number | ''>('')
const newIsDefault = ref(true)

async function openRoutes(p: Product) {
  routeProduct.value = p
  showRouteSheet.value = true
  await loadRoutes()
  if (!allRoutes.value.length) {
    try {
      const res: any = await get('/routes', { params: { page: 1, page_size: 100 } })
      allRoutes.value = (res?.items || res || []).map((r: any) => ({
        id: r.id, code: r.code, name: r.name, version: r.version,
      }))
    } catch { allRoutes.value = [] }
  }
}

async function loadRoutes() {
  if (!routeProduct.value) return
  routeLoading.value = true
  try {
    const res: any = await get(`/products/${routeProduct.value.id}/routes`)
    routeLinks.value = res?.items || []
    routeHasEffectiveDefault.value = !!res?.has_effective_default
  } catch (e: any) {
    showToast(errorText(e, '读取产品工艺路线失败'))
    routeLinks.value = []
  } finally { routeLoading.value = false }
}

async function attachRoute() {
  if (!routeProduct.value || newRouteId.value === '') {
    showToast('请先选择要挂接的工艺路线')
    return
  }
  try {
    const res: any = await post(`/products/${routeProduct.value.id}/routes`, {
      route_id: newRouteId.value,
      is_default: newIsDefault.value,
    })
    // 后端会在 warnings 里说明"第一条自动设为默认""路线尚未发布"这类事，
    // 不能吞 —— 用户否则不知道为什么多了一条默认
    const w = res?.warnings || []
    showToast(w.length ? w[0] : '已挂接')
    newRouteId.value = ''
    await loadRoutes()
  } catch (e: any) {
    showToast(errorText(e, '挂接失败'))
  }
}

async function setDefaultRoute(link: RouteLink) {
  if (!routeProduct.value) return
  try {
    const res: any = await put(
      `/products/${routeProduct.value.id}/routes/${link.id}`, { is_default: true })
    const w = res?.warnings || []
    showToast(w.length ? w[0] : '已设为默认路线')
    await loadRoutes()
  } catch (e: any) {
    showToast(errorText(e, '设置失败'))
  }
}

async function removeRoute(link: RouteLink) {
  if (!routeProduct.value) return
  try {
    const res: any = await del(`/products/${routeProduct.value.id}/routes/${link.id}`)
    const w = res?.warnings || []
    showToast(w.length ? w[0] : '已解除挂接')
    await loadRoutes()
  } catch (e: any) {
    showToast(errorText(e, '解除失败'))
  }
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
  if (typeFilter.value) {
    const hit = PRODUCT_TYPE_OPTIONS.find((o) => o.value === typeFilter.value)
    out.push(`类型「${hit?.label ?? typeFilter.value}」`)
  }
  if (categoryFilter.value) out.push(`分类「${categoryFilter.value}」`)
  conditions.value.forEach((c) => out.push(condText(c)))
  return out
})
const isEmptyFiltered = computed(() => activeFilterTexts.value.length > 0)

function productTypeLabel(v: string): string {
  return PRODUCT_TYPE_OPTIONS.find(o => o.value === v)?.label || v
}

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: 1, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (typeFilter.value) params.product_type = typeFilter.value
    if (categoryFilter.value) params.category = categoryFilter.value
    const res = await get('/products', { params })
    rawList.value = res.items || []
  } catch (e: any) {
    showToast(errorText(e, '获取产品列表失败'))
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  fetchData()
}
function onReset() {
  keyword.value = ''
  typeFilter.value = ''
  categoryFilter.value = ''
  conditions.value = []
  onSearch()
}

function openCreate() {
  isEdit.value = false
  editing.value = {
    code: '',
    name: '',
    spec: '',
    unit: '个',
    product_type: 'final',
    category: '',
    weight: null,
    drawing_url: null,
    is_active: true,
    remark: '',
  }
  showDialog_.value = true
}

function openEdit(item: Product) {
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
      await put(`/products/${data.id}`, data)
      showToast('更新成功')
    } else {
      await post('/products', data)
      showToast('创建成功')
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

async function handleDelete(item: Product) {
  showDialog({
    title: '确认删除',
    message: `确定删除产品「${item.code} - ${item.name}」？`,
    showCancelButton: true,
  }).then(async (action: string) => {
    if (action === 'confirm') {
      try {
        await del(`/products/${item.id}`)
        showToast('删除成功')
        page.value = 1
        fetchData()
      } catch (e: any) {
        showToast(errorText(e, '删除失败'))
      }
    }
  })
}

onMounted(fetchData)
</script>

<template>
  <div class="ziwi-page">
    <!-- 搜索栏：条件 → 输入 → 提交 → 清空 → 查询延伸 | 创建靠右 -->
    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索编码/名称/规格"
      :loading="loading"
      class="ziwi-mb-4"
      @search="onSearch"
      @reset="onReset"
      @advanced="showSearch = true"
    >
      <template #filters>
        <div class="ziwi-w-32">
          <SelectField v-model="typeFilter" :options="PRODUCT_TYPE_OPTIONS" placeholder="产品类型" clearable />
        </div>
        <van-field
          v-model="categoryFilter"
          placeholder="产品分类"
          class="ziwi-list-toolbar__cond"
          clearable
          @keyup.enter="onSearch"
        />
      </template>
      <template #actions>
        <van-button type="success" @click="openCreate">新增产品</van-button>
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
      object-name="产品"
      :conditions="activeFilterTexts"
      primary-text="新增产品"
      @create="openCreate"
      @clear-filter="onReset"
    />
    <div v-else class="prod-table-wrap ziwi-table-scroll">
      <table class="prod-table">
        <thead>
          <tr>
            <th>产品编码</th>
            <th>产品名称</th>
            <th>规格型号</th>
            <th>单位</th>
            <th>产品类型</th>
            <th>产品分类</th>
            <th>状态</th>
            <th class="op">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="item in list" :key="item.id">
            <tr @click="toggleExpand(item.id)">
              <td>{{ item.code }}</td>
              <td>{{ item.name }}</td>
              <td>{{ item.spec || '-' }}</td>
              <td>{{ item.unit }}</td>
              <td>{{ productTypeLabel(item.product_type) }}</td>
              <td>{{ item.category || '-' }}</td>
              <td>
                <van-tag :type="item.is_active ? 'success' : 'danger'" size="small">
                  {{ item.is_active ? '启用' : '禁用' }}
                </van-tag>
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
              <td :colspan="8">
                <ListRowDetail :item="item" :fields="cfg.rowDetailFields" />
                <div class="ziwi-row-actions">
                  <van-button type="primary" plain icon="edit" @click.stop="openEdit(item)">编辑</van-button>
                  <van-button plain icon="guide-o" @click.stop="openRoutes(item)">工艺路线</van-button>
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
      :title="isEdit ? '编辑产品' : '新增产品'"
      :submitting="saving"
      submit-text="保存"
      @submit="handleSave"
    >
      <div class="ziwi-stack-3">
        <van-field v-model="editing.code" label="产品编码" required placeholder="请输入编码" :disabled="isEdit" />
        <van-field v-model="editing.name" label="产品名称" required placeholder="请输入名称" />
        <van-field v-model="editing.spec" label="规格型号" placeholder="可选" />
        <van-field label="产品类型" required>
          <template #input>
            <SelectField v-model="editing.product_type" :options="PRODUCT_TYPE_OPTIONS" class="ziwi-w-full" />
          </template>
        </van-field>
        <van-field v-model="editing.unit" label="单位" required placeholder="个/件/套/Kg/m" />
        <van-field v-model="editing.category" label="产品分类" placeholder="可选" />
        <van-field v-model.number="editing.weight" label="重量(kg)" type="number" placeholder="可选" />
        <van-field label="启用状态">
          <template #input>
            <van-switch v-model="editing.is_active" />
          </template>
        </van-field>
        <van-field v-model="editing.remark" label="备注" type="textarea" rows="2" placeholder="可选" />
      </div>
    </ZiwiFormSheet>

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />

    <!-- 产品 · 默认工艺路线。
         没有默认路线的产品，建工单不会自动带路线 → 报工每条都被判成完工
         → 双口径退化成单口径。所以这一屏要点明"有没有生效中的默认路线"。 -->
    <van-popup v-model:show="showRouteSheet" position="bottom" round
               :style="{ maxHeight: '82%' }">
      <div class="route-sheet">
        <div class="route-sheet__head">
          <div class="route-sheet__title">
            工艺路线 · {{ routeProduct?.name || '' }}
          </div>
          <div class="route-sheet__sub">{{ routeProduct?.code || '' }}</div>
        </div>

        <div class="route-sheet__banner" :class="{ 'is-warn': !routeHasEffectiveDefault }">
          <template v-if="routeHasEffectiveDefault">
            已有生效中的默认路线：建工单不选路线时会自动关联它
          </template>
          <template v-else>
            ⚠️ 没有生效中的默认路线：建工单不会自动带路线，报工将无法按工序归集
          </template>
        </div>

        <van-loading v-if="routeLoading" class="route-sheet__loading" size="20" />

        <van-empty v-else-if="!routeLinks.length" description="还没有挂接任何工艺路线" />

        <div v-else class="route-sheet__list">
          <div v-for="lk in routeLinks" :key="lk.id" class="route-item">
            <div class="route-item__main">
              <div class="route-item__name">
                {{ lk.route_name || '（路线已删除）' }}
                <span class="route-item__ver" v-if="lk.route_version !== null">
                  v{{ lk.route_version }}
                </span>
                <van-tag v-if="lk.is_default" type="primary" class="route-item__tag">默认</van-tag>
                <van-tag v-if="lk.is_default && lk.effective_now === false" type="warning"
                         class="route-item__tag">今天不在生效期</van-tag>
              </div>
              <div class="route-item__meta">
                {{ lk.route_code || '-' }} · {{ lk.step_count ?? 0 }} 道工序
                <span v-if="lk.route_status && lk.route_status !== 'published'"
                      class="route-item__draft">
                  · 未发布（{{ lk.route_status }}）
                </span>
              </div>
              <div class="route-item__meta">
                生效期：{{ lk.effective_from || '不限' }} ~ {{ lk.effective_to || '不限' }}
              </div>
            </div>
            <div class="route-item__ops">
              <van-button v-if="!lk.is_default" size="small" plain type="primary"
                          @click="setDefaultRoute(lk)">设为默认</van-button>
              <van-button size="small" plain type="danger"
                          @click="removeRoute(lk)">解除</van-button>
            </div>
          </div>
        </div>

        <div class="route-sheet__add">
          <van-field label="挂接路线">
            <template #input>
              <van-radio-group v-model="newRouteId" direction="horizontal" class="route-add-group">
                <van-radio v-for="r in allRoutes" :key="r.id" :name="r.id">
                  {{ r.name }}（{{ r.code }}）
                </van-radio>
              </van-radio-group>
              <div v-if="!allRoutes.length" class="route-sheet__hint">
                没有可选的工艺路线，请先在「工艺路线」里新建并发布
              </div>
            </template>
          </van-field>
          <van-cell center title="设为默认路线">
            <template #right-icon>
              <van-switch v-model="newIsDefault" size="20" />
            </template>
          </van-cell>
          <div class="route-sheet__actions">
            <van-button round block type="primary" @click="attachRoute">挂接</van-button>
            <van-button round block plain @click="showRouteSheet = false">关闭</van-button>
          </div>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<style scoped>
.prod-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.prod-table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  font-size: 14px;
  color: var(--ziwi-text-primary, #1e293b);
  background: var(--ziwi-bg, #fff);
}

.prod-table thead th {
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

.prod-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  text-align: left;
  vertical-align: middle;
  color: var(--ziwi-text-primary, #1e293b);
}

.prod-table tbody td.op {
  text-align: right;
  white-space: normal;
}

/* .op-btns 已随行内操作移入展开区删除（改用共享类 .ziwi-row-actions）。
   顺带去掉 max-width: 220px —— 那是为了在窄列里硬挤 3 个图标键的补丁。 */

/* 行展开（并集详情）整行底色弱化，凸显多列并排明细 */
/* 数据行本身是"点行展开"的点击目标，必须 ≥ --ziwi-touch-min（同 WorkCenterList：
   拿走行内图标键后行高会从 46 掉到 40，原来是 mini 按钮在撑行高）。 */
.prod-table tbody tr:not(.row-detail-row) {
  height: var(--ziwi-touch-min);
}

.prod-table tbody tr.row-detail-row td {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.02));
  padding: 0;
  /* B-15：colspan 单元格必须能收缩。不加这条时 td 被明细网格撑到 1845px，
     .rd-scroll 的 clientWidth == scrollWidth（没有可滚动基准）→ 网格被表格
     祖先裁掉，1440 屏下末 4 个字段既看不见也滚不到。max-width:0 让 td 收缩到
     表宽，子元素 overflow 才真正生效。 */
  max-width: 0;
}

.prod-table tbody tr:hover:not(.row-detail-row) {
  background: var(--ziwi-row-hover, rgba(0, 0, 0, 0.04));
}

@media (max-width: 768px) {
  .prod-table {
    font-size: 13px;
  }
  .prod-table thead th,
  .prod-table tbody td {
    padding: 8px 10px;
  }
}

/* ── 产品工艺路线弹层 ─────────────────────────────────────────── */
.route-sheet {
  padding: var(--ziwi-gap-md, 12px) var(--ziwi-gap-md, 12px) calc(var(--ziwi-gap-md, 12px) + env(safe-area-inset-bottom));
}
.route-sheet__head { margin-bottom: 8px; }
.route-sheet__title { font-size: 16px; font-weight: 600; }
.route-sheet__sub { font-size: 12px; color: var(--ziwi-text-2, #646566); margin-top: 2px; }

.route-sheet__banner {
  font-size: 13px;
  line-height: 1.5;
  padding: 8px 10px;
  border-radius: 8px;
  background: #eef7ee;
  color: #2e7d32;
  margin-bottom: 10px;
}
/* 没有默认路线是"会让数据口径出问题"的状态，用警示色而不是安静灰 */
.route-sheet__banner.is-warn { background: #fff7e6; color: #b26a00; }

.route-sheet__loading { padding: 24px 0; text-align: center; }
.route-sheet__list { max-height: 42vh; overflow-y: auto; }

.route-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
}
.route-item__main { flex: 1; min-width: 0; }
.route-item__name { font-size: 14px; font-weight: 500; }
.route-item__ver { font-size: 12px; color: var(--ziwi-text-2, #969799); margin-left: 4px; }
.route-item__tag { margin-left: 6px; }
.route-item__meta { font-size: 12px; color: var(--ziwi-text-2, #646566); margin-top: 3px; }
.route-item__draft { color: #b26a00; }
.route-item__ops { display: flex; flex-direction: column; gap: 6px; flex: 0 0 auto; }

.route-sheet__add { margin-top: 12px; }
.route-add-group { display: flex; flex-direction: column; gap: 4px; max-height: 22vh; overflow-y: auto; }
.route-sheet__hint { font-size: 12px; color: var(--ziwi-text-2, #969799); }
.route-sheet__actions { display: flex; gap: 10px; margin-top: 12px; }
</style>
