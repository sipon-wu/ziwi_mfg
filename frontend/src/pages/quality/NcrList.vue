<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { showToast } from 'vant'
import { get, post, put } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'
import ZiwiListToolbar from '@/components/ziwi/ZiwiListToolbar.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import { statusTagOf } from '@/composables/useStatusTag'
import { enumLabel, enumOptions } from '@/config/enums'
import { useDrilldown } from '@/composables/useDrilldown'
import DrilldownBanner from '@/components/ziwi/DrilldownBanner.vue'

// M30 不合格品评审（NCR）
// 每次状态推进都会写入后端通用状态流水，轨迹可在「流转记录」中查看
const drill = useDrilldown()
const drillActive = drill.active
const items = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage, loadFailed } = usePagination()
const keyword = ref('')
const statusFilter = ref('')

// 状态 / 来源 / 处置方式统一走中央字典（config/statusDict.ts + config/enums.ts）。
// 原来自建的 STATUS_MAP 少了 `in_progress`/`completed`/`verified` 三种后端声明值，
// 而 `|| item.status` 兜底又让缺失的值直接印成英文 —— 两头都不对。
const statusOptions = [
  { value: '', label: '全部' },
  { value: 'open', label: '待评审' },
  { value: 'reviewing', label: '评审中' },
  { value: 'disposed', label: '已处置' },
  { value: 'closed', label: '已关闭' },
]

// 处置方式从字典推（后端值域：return/sorting/concession/rework/scrap/claim）。
// ★ 这里原先是 `DISPOSITION_MAP` 本地常量，中文化改造删掉后模板仍在 v-for 它
//   —— 不报错、不掉接口，只是**整块处置标签渲染成空白**，处置弹窗变成单选不了。
const dispositionOptions = enumOptions('disposition')

// 各状态允许的下一步（与后端 NCR_TRANSITIONS 一致）
const NEXT_ACTIONS: Record<string, { to: string; label: string }[]> = {
  open: [
    { to: 'reviewing', label: '开始评审' },
    { to: 'disposed', label: '直接处置' },
  ],
  reviewing: [{ to: 'disposed', label: '处置' }, { to: 'closed', label: '关闭' }],
  disposed: [{ to: 'closed', label: '关闭' }],
}

/** 加载/空/失败三分（UE-09/12）：失败不再伪装成「暂无数据」 */
const pageState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (items.value?.length) return 'ready'
  if (loading.value) return 'loading'
  return !!keyword.value ? 'empty-filtered' : 'empty-true'
})

async function loadData() {
  if (drill.active.value) {
    // 下探视图：替换式取数，不追加、不分页
    const r = await drill.loadMerged<any>('/ncr')
    items.value = r.items
    total.value = r.total
    return
  }
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (statusFilter.value) params.status = statusFilter.value
  const data = await fetchPage(async (p) => {
    return get<PaginatedResponse<any>>('/ncr', { ...params, ...p })
  })
  items.value = [...items.value, ...(data as any[])]
}

function onStatusChange() {
  // 下探视图里点状态标签 = 想按标签浏览，先清下探条件再由 onChange 重取
  if (drill.active.value) { drill.clear(); return }
  items.value = []
  resetPage()
  loadData()
}

/** 工具栏「重置」= 清关键词 + 状态筛选 + 回第一页 */
function onReset() {
  keyword.value = ''
  statusFilter.value = ''
  onStatusChange()
}

onMounted(() => {
  items.value = []
  loadData()
})
// 清除下探 / 换一张 KPI 卡下探进来时组件不重挂载，必须显式重新取数
drill.onChange(() => { items.value = []; resetPage(); void loadData() })

// ── 新建 ──
const showCreate = ref(false)
const form = ref<any>({ ncr_no: '', source_type: 'iqc', defect_qty: null, severity: 'major', defect_desc: '' })
const SOURCE_OPTIONS = ['iqc', 'ipqc', 'fqc', 'oqc', 'lab', 'manual']
const SEVERITY_OPTIONS = [
  { value: 'minor', label: '一般' },
  { value: 'major', label: '严重' },
  { value: 'critical', label: '重大' },
]

function openCreate() {
  form.value = {
    ncr_no: `NC-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${String(Date.now()).slice(-4)}`,
    source_type: 'iqc',
    defect_qty: null,
    severity: 'major',
    defect_desc: '',
  }
  showCreate.value = true
}

async function submitCreate() {
  if (!form.value.ncr_no) {
    showToast('请填写单号')
    return
  }
  // 数值选填字段空串 → null，避免后端 Optional[float] 解析失败（van-field type=number 空值会变 ""）
  const payload: any = { ...form.value }
  if (payload.defect_qty === '' || payload.defect_qty === null || payload.defect_qty === undefined) {
    payload.defect_qty = null
  } else {
    payload.defect_qty = Number(payload.defect_qty)
  }
  try {
    await post('/ncr', payload)
    showToast('已创建')
    showCreate.value = false
    onStatusChange()
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '创建失败')
  }
}

// ── 处置 ──
const showDispose = ref(false)
const disposeForm = ref<any>({ id: null, disposition: 'return', disposition_remark: '' })
function openDispose(item: any) {
  disposeForm.value = { id: item.id, disposition: 'return', disposition_remark: '' }
  showDispose.value = true
}
async function submitDispose() {
  try {
    await put(`/ncr/${disposeForm.value.id}/status`, {
      to_status: 'disposed',
      disposition: disposeForm.value.disposition,
      disposition_remark: disposeForm.value.disposition_remark,
    })
    showToast('已处置')
    showDispose.value = false
    onStatusChange()
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '操作失败')
  }
}

// ── 状态推进 ──
async function advance(item: any, toStatus: string) {
  if (toStatus === 'disposed') {
    openDispose(item)
    return
  }
  try {
    await put(`/ncr/${item.id}/status`, { to_status: toStatus })
    showToast('已更新')
    onStatusChange()
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '操作失败')
  }
}

// ── 流转记录（来自通用状态流水）──
const showTrail = ref(false)
const trail = ref<any[]>([])
const trailTitle = ref('')
async function openTrail(item: any) {
  trailTitle.value = item.ncr_no
  const res = await get<any>(`/ncr/${item.id}/trail`)
  trail.value = (res as any).data || res || []
  showTrail.value = true
}
function fmtTime(t: string) {
  return t ? String(t).replace('T', ' ').slice(0, 19) : '-'
}
</script>

<template>
  <div>
    <DrilldownBanner :total="total" />
    <van-cell-group title="不合格品评审（NCR）">
      <van-cell title="单据总数" :value="total" />
    </van-cell-group>

    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索 NCR 单号/来源单号"
      :loading="loading"
      @search="onStatusChange"
      @reset="onReset"
    >
      <template #actions>
        <van-button v-perm="'M30:ncr:create'" type="success" @click="openCreate">新建 NCR</van-button>
      </template>
    </ZiwiListToolbar>

    <div style="display:flex; gap:8px; margin:12px 16px; flex-wrap:wrap;">
      <van-tag v-for="opt in statusOptions" :key="opt.value"
        :type="statusFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor: 'pointer', padding: '4px 12px' }"
        @click="statusFilter = opt.value; onStatusChange()"
      >{{ opt.label }}</van-tag>
    </div>

    <van-list v-model:loading="loading" :finished="drillActive || !total || items.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in items" :key="item.id">
        <template #title>
          {{ item.ncr_no }}
          <van-tag :type="statusTagOf('ncr', item.status).tagType" style="margin-left:6px">
            {{ statusTagOf('ncr', item.status).label }}
          </van-tag>
        </template>
        <template #label>
          <div>来源：{{ enumLabel('ncr_source', item.source_type) }}<span v-if="item.source_no">（{{ item.source_no }}）</span></div>
          <div v-if="item.defect_qty != null">不良数：{{ item.defect_qty }}</div>
          <div v-if="item.disposition">处置：{{ enumLabel('disposition', item.disposition) }}</div>
          <div v-if="item.defect_desc" style="color:#888">{{ item.defect_desc }}</div>
          <div style="margin-top:6px; display:flex; gap:6px; flex-wrap:wrap;">
            <van-button
              v-for="act in NEXT_ACTIONS[item.status] || []"
              v-perm="'M30:ncr_status:update'"
              :key="act.to"
              size="mini"
              type="primary"
              plain
              @click="advance(item, act.to)"
            >{{ act.label }}</van-button>
            <van-button v-if="['open', 'reviewing', 'disposed'].includes(item.status)"
              v-perm="'M30:ncr_status:update'"
              size="mini" plain type="danger" @click="advance(item, 'cancelled')">作废</van-button>
            <van-button size="mini" plain icon="orders-o" @click="openTrail(item)">流转记录</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>

    <ZiwiStateView
      v-if="pageState !== 'ready'"
      :state="pageState"
      object-name="不合格评审单"
      @retry="loadData"
    />

    <!-- 新建 -->
    <van-popup v-model:show="showCreate" position="bottom" :style="{ height: '80%' }" round>
      <div style="padding:16px">
        <h3 style="margin:0 0 12px">新建不合格评审单</h3>
        <van-field v-model="form.ncr_no" label="单号" placeholder="NC-..." required />
        <van-field label="来源类型">
          <template #input>
            <van-tag v-for="s in SOURCE_OPTIONS" :key="s"
              :type="form.source_type === s ? 'primary' : 'default'"
              style="margin-right:6px;cursor:pointer" @click="form.source_type = s">{{ s }}</van-tag>
          </template>
        </van-field>
        <van-field v-model="form.defect_qty" label="不良数量" type="number" placeholder="选填" />
        <van-field label="严重度">
          <template #input>
            <van-tag v-for="s in SEVERITY_OPTIONS" :key="s.value"
              :type="form.severity === s.value ? 'primary' : 'default'"
              style="margin-right:6px;cursor:pointer" @click="form.severity = s.value">{{ s.label }}</van-tag>
          </template>
        </van-field>
        <van-field v-model="form.defect_desc" label="不良描述" type="textarea" rows="3" placeholder="选填" />
        <van-button type="primary" block style="margin-top:16px" @click="submitCreate">提交</van-button>
      </div>
    </van-popup>

    <!-- 处置 -->
    <van-popup v-model:show="showDispose" position="bottom" round :style="{ height: '55%' }">
      <div style="padding:16px">
        <h3 style="margin:0 0 12px">不合格处置</h3>
        <van-field label="处置方式">
          <template #input>
            <div>
              <van-tag v-for="opt in dispositionOptions" :key="opt.value"
                :type="disposeForm.disposition === opt.value ? 'primary' : 'default'"
                style="margin:0 6px 6px 0;cursor:pointer"
                @click="disposeForm.disposition = opt.value">{{ opt.text }}</van-tag>
            </div>
          </template>
        </van-field>
        <van-field v-model="disposeForm.disposition_remark" label="处置说明" type="textarea" rows="3" />
        <van-button type="primary" block style="margin-top:16px" @click="submitDispose">确认处置</van-button>
      </div>
    </van-popup>

    <!-- 流转记录 -->
    <van-popup v-model:show="showTrail" position="bottom" round :style="{ height: '60%' }">
      <div style="padding:16px">
        <h3 style="margin:0 0 12px">流转记录 · {{ trailTitle }}</h3>
        <ZiwiStateView
      v-if="!trail.length"
      state="empty-true"
      object-name="流转记录"
    />
        <van-cell v-for="(t, i) in trail" :key="i"
          :title="`${statusTagOf('ncr', t.to_status).label}（${t.action || '-'}）`"
          :label="`${fmtTime(t.occurred_at)} · ${t.actor_name || '系统'}${t.reason ? ' · ' + t.reason : ''}`" />
      </div>
    </van-popup>
  </div>
</template>
