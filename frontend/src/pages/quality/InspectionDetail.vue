<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post, put, errorText } from '@/api/client'
import { showToast } from 'vant'
import { useAuthStore } from '@/stores/auth'
import { useStatusTag } from '@/composables/useStatusTag'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canJudge = computed(() => auth.hasPerm('M03:inspection_order:approve'))
// 录入与判定是两条权限：判定是"下结论"，录入是"填数"。
// 现场常见的是检验员录数、品保主管判定 —— 合成一条权限就只能让两个人共账号。
const canEntry = computed(() =>
  auth.hasPerm('M03:inspection_order_result:execute')
  || auth.hasPerm('M03:inspection_order:update'))

// 对齐后端：order_type ∈ first/inspection/spot_check；
// result ∈ ACC/REJ/UAI，**空 = 未判定**（C-79 起建单不再写 'pending' 占位）
const ORDER_TYPE_MAP: Record<string, string> = {
  first: '首件检验',
  inspection: '过程检验',
  spot_check: '抽检',
}
// 录入通道：同一个数，手抄 / 手机录 / 量具直采的可信度完全不同
/** 状态标签：文案/图标/语义统一取自 config/statusDict.ts（UE §1.2 双编码） */
const statusTagCache = new Map<string, ReturnType<typeof useStatusTag>>()
function statusTagOf(code: string): ReturnType<typeof useStatusTag> {
  let tag = statusTagCache.get(code)
  if (!tag) {
    tag = useStatusTag('inspection_result', code)
    statusTagCache.set(code, tag)
  }
  return tag
}

const SOURCE_MAP: Record<string, string> = {
  web: 'PC 录入',
  miniapp: '小程序',
  device: '设备直连',
}

const order = ref<any>(null)
const loading = ref(false)

/** 详情三分：加载中 / 不存在 / 已就绪。原先「加载中」被写成 van-empty 的描述 */
const detailState = computed<StateKind>(() => {
  if (order.value) return 'ready'
  return loading.value ? 'loading' : 'empty-true'
})
const results = ref<any[]>([])
const items = ref<any[]>([])
const judging = ref(false)
const submitting = ref(false)

// 录入草稿行：一次可以填多项再一起提交（现场是"一整套量完再录"，
// 逐条提交会让人反复点 6 次保存）
type Draft = {
  item_id: number | null
  item_name: string
  measured_value: string
  result: string        // '' = 自动判定
  remark: string
}
const drafts = ref<Draft[]>([])
const showPicker = ref(false)
const activeRow = ref(0)

const itemColumns = computed(() =>
  items.value.map((i) => ({ text: i.item_name, value: i.id })))

const judged = computed(() => !!order.value?.result)
const filledDrafts = computed(() =>
  drafts.value.filter((d) => d.item_id || d.item_name || d.measured_value !== ''))

function specText(item: any) {
  if (!item) return ''
  const up = item.spec_upper_limit
  const lo = item.spec_lower_limit
  if (up == null && lo == null) return ''
  if (up != null && lo != null) return `${lo}~${up}`
  if (up != null) return `≤${up}`
  return `≥${lo}`
}

// 后端时间戳有两种形态（SQLite 出来的 'YYYY-MM-DD HH:MM:SS'、
// 新写入的带微秒与时区的 ISO），原样显示成
// "2026-11-01 10:33:11.850327+00:00" 现场没人看得下去。
function fmtTime(v?: string) {
  if (!v) return '-'
  return String(v).replace('T', ' ').slice(0, 16)
}

function draftSpec(d: Draft) {
  const it = items.value.find((i) => i.id === d.item_id)
  return it ? specText(it) : ''
}

async function fetch() {
  loading.value = true
  try {
    order.value = await get(`/inspection-orders/${route.params.id}`)
    results.value = (await get(`/inspection-orders/${route.params.id}/results`)) as any
  } catch (e) {
    showToast(errorText(e, '检验单加载失败'))
  } finally {
    loading.value = false
  }
}

async function fetchItems() {
  const d: any = await get('/inspection-items', { page: 1, page_size: 100 })
  items.value = d?.items || []
}

function addRow() {
  drafts.value.push({
    item_id: null, item_name: '', measured_value: '', result: '', remark: '',
  })
}

function removeRow(i: number) {
  drafts.value.splice(i, 1)
}

function openPicker(i: number) {
  activeRow.value = i
  showPicker.value = true
}

function onPick({ selectedValues }: any) {
  const id = Array.isArray(selectedValues) ? selectedValues[0] : selectedValues
  const it = items.value.find((x) => x.id === id)
  const d = drafts.value[activeRow.value]
  if (d && it) {
    d.item_id = it.id
    d.item_name = it.item_name
  }
  showPicker.value = false
}

async function submitResults() {
  const rows = filledDrafts.value
  if (!rows.length) {
    showToast('请先填至少一项检验结果')
    return
  }
  submitting.value = true
  try {
    const res: any = await post(
      `/inspection-orders/${route.params.id}/results/batch`,
      {
        source: 'web',
        results: rows.map((d) => ({
          item_id: d.item_id || null,
          item_name: d.item_name || null,
          measured_value: d.measured_value === '' ? null : Number(d.measured_value),
          result: d.result || null,
          remark: d.remark || null,
        })),
      },
    )
    const parts = []
    if (res?.created) parts.push(`新增 ${res.created} 项`)
    if (res?.updated) parts.push(`复测更新 ${res.updated} 项`)
    if (res?.failed_items?.length) parts.push(`不合格：${res.failed_items.join('、')}`)
    showToast(parts.join('，') || '已录入')
    // 人工结论与限值矛盾时必须当场告诉人（让步接收要留痕，不能静默）
    if (res?.conflicts?.length) {
      showToast({ message: `数值与结论不一致：${res.conflicts[0]}`, duration: 5000 })
    }
    // 提交后立刻补一行空行：现场是"一整套量完再录"，录完手还在键盘上，
    // 让界面变回"零行 + 一个添加按钮"等于逼人多点一次。
    drafts.value = []
    addRow()
    await fetch()
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '录入失败')
  } finally {
    submitting.value = false
  }
}

async function judge(result: string) {
  judging.value = true
  try {
    const res: any = await put(`/inspection-orders/${route.params.id}/judge`, { result })
    if (result === 'REJ' && res?.ncr_id) {
      showToast(`已自动发起不合格评审 #${res.ncr_id}`)
    } else if (result === 'ACC') {
      showToast('判定为合格')
    } else if (result === 'UAI') {
      showToast('已标记待判定')
    } else {
      showToast('判定完成')
    }
    await fetch()
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '判定失败')
  } finally {
    judging.value = false
  }
}

onMounted(async () => {
  await Promise.all([fetch(), fetchItems()])
  if (!judged.value) addRow()
})

/**
 * T04 检验执行页入口。
 *
 * 详情页保留"随手改一行"的轻录入，但**成套录数必须走执行页**：
 * 执行页按 `/checklist` 给本单应检项，不依赖"全站前 100 项"的下拉。
 */
function goExecute() {
  router.push(`/quality/${route.params.id}/execute`)
}
</script>

<template>
  <div v-if="order">
    <van-nav-bar title="检验详情" left-arrow @click-left="() => router.push('/quality')" />
    <div style="padding:16px;">
      <van-cell-group title="检验单信息">
        <van-cell title="检验单号" :value="order.order_no || ('#' + order.id)" />
        <van-cell title="检验类型" :value="ORDER_TYPE_MAP[order.order_type] || order.order_type || '-'" />
        <van-cell title="判定结果" :value="statusTagOf(order.result).label.value" />
        <van-cell v-if="order.ac != null" title="抽样方案"
          :value="`样本 ${order.sample_qty ?? '-'} · Ac ${order.ac} / Re ${order.re}`" />
        <van-cell title="创建时间" :value="fmtTime(order.created_at)" />
        <van-cell v-if="order.remark" title="备注" :value="order.remark" />
      </van-cell-group>

      <!-- T04：成套录数走执行页（按本单应检项逐项卡片，不用在下拉里翻 100 项） -->
      <van-button
        v-if="!judged"
        type="primary"
        block
        style="margin-top:12px;min-height:var(--ziwi-touch-min);"
        @click="goExecute"
      >
        {{ ORDER_TYPE_MAP[order.order_type] || '检验' }}执行（逐项录数）
      </van-button>

      <!-- 已录明细：现场最常问"这项到底测了没、测的多少" -->
      <van-cell-group title="检验明细" style="margin-top:12px;">
        <div v-if="!results.length" style="padding:12px;color:#969799;font-size:13px">
          还没有录入任何检验结果
        </div>
        <div v-for="r in results" :key="r.id"
          style="padding:10px 12px;border-bottom:1px solid #f2f3f5;">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span style="font-weight:500;">{{ r.item_name || ('项#' + r.item_id) }}</span>
            <van-tag v-if="r.spec_value" plain type="primary">{{ r.spec_value }}</van-tag>
            <van-tag :type="r.result === 'FAIL' ? 'danger' : r.result === 'PASS' ? 'success' : 'default'">
              {{ r.result === 'FAIL' ? '不合格' : r.result === 'PASS' ? '合格' : '未判' }}
            </van-tag>
            <van-tag plain>{{ SOURCE_MAP[r.source] || r.source || 'PC 录入' }}</van-tag>
          </div>
          <div style="color:#646566;font-size:13px;margin-top:4px;">
            实测 {{ r.measured_value ?? '-' }}{{ r.unit || '' }}
            <span v-if="r.device_code"> · 设备 {{ r.device_code }}</span>
            <span v-if="r.measured_at"> · {{ fmtTime(r.measured_at) }}</span>
          </div>
          <div v-if="r.remark" style="color:#969799;font-size:12px;margin-top:2px;">{{ r.remark }}</div>
        </div>
      </van-cell-group>

      <!-- 结果录入 -->
      <van-cell-group title="结果录入" style="margin-top:12px;">
        <div v-if="judged" style="padding:12px;color:#969799;font-size:13px">
          该单已判定（{{ statusTagOf(order.result).label.value }}），明细不可再修改。
          判定是终态结论，判完还能改数等于判定依据被篡改；如需复检请新建检验单。
        </div>
        <template v-else>
          <div v-for="(d, i) in drafts" :key="i"
            style="padding:10px 12px;border-bottom:1px solid #f2f3f5;">
            <van-field
              :model-value="d.item_name || ''"
              label="检验项" placeholder="选择检验项" readonly is-link
              @click="openPicker(i)"
            />
            <div v-if="draftSpec(d)" style="padding:0 0 4px 16px;color:#969799;font-size:12px;">
              规格 {{ draftSpec(d) }}
            </div>
            <van-field v-model="d.measured_value" label="实测值" type="number"
              placeholder="只填数值即可，按规格自动判定" />
            <van-field label="结论">
              <template #input>
                <van-radio-group v-model="d.result" direction="horizontal">
                  <van-radio name="">自动</van-radio>
                  <van-radio name="PASS">合格</van-radio>
                  <van-radio name="FAIL">不合格</van-radio>
                </van-radio-group>
              </template>
            </van-field>
            <van-field v-model="d.remark" label="备注" placeholder="让步接收等需在此说明" />
            <div style="text-align:right;">
              <van-button size="mini" plain type="danger" @click="removeRow(i)">删除本行</van-button>
            </div>
          </div>
          <div style="padding:12px;display:flex;gap:10px;">
            <van-button size="small" plain type="primary" @click="addRow">添加一行</van-button>
            <van-button size="small" type="primary" :loading="submitting"
              :disabled="!canEntry || !filledDrafts.length" @click="submitResults">
              提交录入（{{ filledDrafts.length }} 项）
            </van-button>
          </div>
          <div v-if="!canEntry" style="padding:0 12px 12px;color:#969799;font-size:13px">
            录入需要「检验结果录入」权限（M03:inspection_order_result:execute），你的角色没有开通
          </div>
        </template>
      </van-cell-group>

      <van-cell-group title="判定" style="margin-top:12px;">
        <div style="padding:12px; display:flex; gap:10px;">
          <van-button v-perm="'M03:inspection_order:approve'" type="success" size="small" :loading="judging" @click="judge('ACC')">合格</van-button>
          <van-button v-perm="'M03:inspection_order:approve'" type="danger" size="small" :loading="judging" @click="judge('REJ')">不合格</van-button>
          <van-button v-perm="'M03:inspection_order:approve'" type="warning" size="small" :loading="judging" @click="judge('UAI')">待判定</van-button>
        </div>
        <div v-if="!canJudge" style="padding:0 12px 12px;color:#969799;font-size:13px">
          判定需要「检验判定」权限（M03:inspection_order:approve），你的角色没有开通
        </div>
        <van-cell
          v-if="order.result === 'REJ'"
          title="已自动发起不合格评审（NCR）"
          is-link
          @click="router.push('/quality/ncr')"
          value="查看"
        />
      </van-cell-group>
    </div>

    <van-popup v-model:show="showPicker" position="bottom" round>
      <van-picker
        :columns="itemColumns"
        @confirm="onPick"
        @cancel="showPicker = false"
      />
    </van-popup>
  </div>
  <ZiwiStateView v-else :state="detailState" skeleton="detail" object-name="检验单" />
</template>
