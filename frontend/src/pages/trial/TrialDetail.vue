<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showDialog, showToast, showLoadingToast, closeToast } from 'vant'
import { getTrial, getTrialRoute, saveTrialRoute, getTrialBom, saveTrialBom, listReviews, submitReview, makeReviewDecision, advanceStage, convertToProduction, terminateTrial } from '@/api/trial'
import type { TrialOrder, TrialRoute, TrialBom, TrialReview } from '@/api/trial'

const route = useRoute()
const router = useRouter()
const orderId = Number(route.params.id)

const order = ref<TrialOrder | null>(null)
const trialRoute = ref<TrialRoute | null>(null)
const trialBom = ref<TrialBom | null>(null)
const reviews = ref<TrialReview[]>([])
const activeTab = ref(0)
const loading = ref(false)

const routeText = ref('')
const bomText = ref('')

const statusMap: Record<string, string> = {
  planning: '规划', lab_trial: '小试', pilot_run: '中试',
  batch_verify: '小批量验证', review: '评审', production: '转量产', terminated: '已终止',
}
const STAGE_ORDER = ['planning', 'lab_trial', 'pilot_run', 'batch_verify', 'review']
const typeMap: Record<string, string> = {
  new_product: '新产品试产', new_process: '新工艺试产', new_material: '新材料试产',
  eco_verification: '工程变更验证', tooling_trial: '模具/工装验证',
}

const conclusionMap: Record<string, string> = {
  pending: '待评审', approved: '通过', conditional_approve: '有条件通过',
  terminated: '终止', adjust: '需调整',
}

const skipInfo = computed(() => {
  if (!order.value) return ''
  const t = order.value.trial_type
  if (t === 'new_process') return '新工艺类型：可跳过「小试」阶段'
  if (t === 'new_material') return '新材料类型：可跳过「中试」阶段'
  if (t === 'eco_verification') return '工程变更类型：可直接进入「小批量验证」'
  if (t === 'tooling_trial') return '模具验证类型：可直接进入「小批量验证」'
  return ''
})

async function fetchAll() {
  loading.value = true
  try {
    order.value = await getTrial(orderId) as any
    const r = await getTrialRoute(orderId) as any
    trialRoute.value = r.id ? r : null
    const b = await getTrialBom(orderId) as any
    trialBom.value = b.id ? b : null
    reviews.value = await listReviews(orderId) as any
    if (trialRoute.value?.route_json) {
      routeText.value = typeof trialRoute.value.route_json === 'string'
        ? trialRoute.value.route_json : JSON.stringify(trialRoute.value.route_json, null, 2)
    }
    if (trialBom.value?.bom_json) {
      bomText.value = typeof trialBom.value.bom_json === 'string'
        ? trialBom.value.bom_json : JSON.stringify(trialBom.value.bom_json, null, 2)
    }
  } finally { loading.value = false }
}

onMounted(fetchAll)

function goBack() { router.push('/trials') }

async function handleAdvance() {
  if (!order.value) return
  const skipStages: Record<string, string> = {
    planning: 'lab_trial', lab_trial: 'pilot_run', pilot_run: 'batch_verify', batch_verify: 'review',
  }
  const next = skipStages[order.value.status]
  if (!next) { showToast('当前阶段无法推进'); return }
  try {
    await showConfirmDialog({ title: '阶段推进', message: `从 ${statusMap[order.value.status]} 推进到 ${statusMap[next]}？\n${skipInfo.value}` })
    await advanceStage(order.value.id)
    showToast('推进成功')
    fetchAll()
  } catch { /* cancelled */ }
}

async function handleSaveRoute() {
  if (!order.value) return
  try {
    let parsed: any
    try { parsed = JSON.parse(routeText.value) } catch { showToast('JSON 格式错误'); return }
    await saveTrialRoute(order.value.id, { route_json: parsed })
    showToast('路线已保存')
    fetchAll()
  } catch { showToast('保存失败') }
}

async function handleSaveBom() {
  if (!order.value) return
  try {
    let parsed: any
    try { parsed = JSON.parse(bomText.value) } catch { showToast('JSON 格式错误'); return }
    await saveTrialBom(order.value.id, { bom_json: parsed })
    showToast('BOM已保存')
    fetchAll()
  } catch { showToast('保存失败') }
}

async function handleSubmitReview() {
  if (!order.value) return
  try {
    await showConfirmDialog({ title: '提交评审', message: '确定提交试产评审？' })
    await submitReview(order.value.id, { review_items: [] })
    showToast('评审已提交')
    fetchAll()
  } catch { /* cancelled */ }
}

async function handleReviewDecision(reviewId: number, conclusion: string) {
  if (!order.value) return
  try {
    await showConfirmDialog({ title: '评审决策', message: `确定评审结论为「${conclusionMap[conclusion] || conclusion}」？` })
    await makeReviewDecision(order.value.id, reviewId, { conclusion })
    showToast('决策已提交')
    fetchAll()
  } catch { /* cancelled */ }
}

async function handleConvert() {
  if (!order.value) return
  try {
    await showConfirmDialog({ title: '转量产', message: '确定一键转量产？此操作将创建正式数据' })
    await convertToProduction(order.value.id)
    showToast('转量产成功')
    fetchAll()
  } catch { /* cancelled */ }
}

async function handleTerminate() {
  if (!order.value) return
  try {
    await showConfirmDialog({ title: '终止试产', message: '确定终止此试产工单？' })
    await terminateTrial(order.value.id)
    showToast('已终止')
    fetchAll()
  } catch { /* cancelled */ }
}
</script>

<template>
  <div>
    <van-nav-bar :title="order?.order_no || '试产详情'" left-arrow @click-left="goBack" />
    <div v-if="loading"><van-loading style="margin-top: 40px" /></div>
    <div v-else-if="order">
      <!-- 基本信息 -->
      <van-cell-group title="基本信息">
        <van-cell title="工单编号" :value="order.order_no" />
        <van-cell title="试产类型" :value="typeMap[order.trial_type] || order.trial_type" />
        <van-cell title="当前阶段">
          <van-tag :type="order.status === 'production' ? 'success' : order.status === 'terminated' ? 'danger' : 'primary'" size="medium">
            {{ statusMap[order.status] || order.status }}
          </van-tag>
        </van-cell>
        <van-cell title="产品" :value="order.product_name" />
        <van-cell v-if="order.product_spec" title="产品规格" :value="order.product_spec" />
        <van-cell title="计划数量" :value="order.planned_qty?.toString() || '-'" />
        <van-cell title="已完成" :value="order.completed_qty?.toString() || '0'" />
        <van-cell title="优先级" :value="order.priority?.toString() || '500'" />
        <van-cell title="实验室检测" :value="order.lab_required ? '需要' : '不需要'" />
        <van-cell v-if="order.started_at" title="开始时间" :value="order.started_at?.slice(0, 19).replace('T', ' ')" />
        <van-cell v-if="order.completed_at" title="完成时间" :value="order.completed_at?.slice(0, 19).replace('T', ' ')" />
        <van-cell v-if="order.terminated_reason" title="终止原因" :value="order.terminated_reason" />
      </van-cell-group>

      <!-- 操作按钮 -->
      <div style="padding: 12px 16px">
        <van-space direction="vertical" fill>
          <van-button v-if="['planning', 'lab_trial', 'pilot_run', 'batch_verify'].includes(order.status)" block type="primary" @click="handleAdvance">
            阶段推进 ({{ statusMap[order.status] }} → 下一阶段)
          </van-button>
          <van-button v-if="order.status === 'review'" block type="success" @click="handleConvert">
            一键转量产
          </van-button>
          <van-button v-if="!['production', 'terminated'].includes(order.status)" block type="warning" @click="handleTerminate">
            终止试产
          </van-button>
        </van-space>
        <div v-if="skipInfo" style="margin-top: 8px; font-size: 12px; color: #999">{{ skipInfo }}</div>
      </div>

      <!-- 页签 -->
      <van-tabs v-model:active="activeTab">
        <van-tab title="试产BOM">
          <div style="padding: 12px">
            <van-field v-model="bomText" type="textarea" rows="12" placeholder="请输入JSON格式的BOM数据" />
            <van-space style="margin-top: 8px">
              <van-button size="small" type="primary" @click="handleSaveBom">保存BOM</van-button>
              <van-button size="small" @click="bomText = '[]'">清空</van-button>
            </van-space>
          </div>
        </van-tab>
        <van-tab title="试产路线">
          <div style="padding: 12px">
            <van-field v-model="routeText" type="textarea" rows="12" placeholder="请输入JSON格式的路线数据" />
            <van-space style="margin-top: 8px">
              <van-button size="small" type="primary" @click="handleSaveRoute">保存路线</van-button>
              <van-button size="small" @click="routeText = '[]'">清空</van-button>
            </van-space>
          </div>
        </van-tab>
        <van-tab title="阶段推进">
          <div style="padding: 12px">
            <van-cell-group>
              <van-cell title="当前阶段" :value="statusMap[order.status] || order.status" />
              <van-cell title="试产类型" :value="typeMap[order.trial_type] || order.trial_type" />
            </van-cell-group>
            <div v-if="skipInfo" style="margin: 12px 0; padding: 8px; background: #fff8e1; border-radius: 4px; font-size: 13px; color: #795548">{{ skipInfo }}</div>
            <div style="margin-top: 12px">
              <div style="display: flex; align-items: center; gap: 4px; flex-wrap: wrap">
                <van-tag v-for="(s, i) in ['planning', 'lab_trial', 'pilot_run', 'batch_verify', 'review']" :key="s"
                  :type="order.status === s ? 'primary' : STAGE_ORDER.indexOf(s) < STAGE_ORDER.indexOf(order.status) ? 'success' : 'default'" size="medium">
                  {{ statusMap[s] }}
                </van-tag>
                <span v-if="i < 4" style="color: #999">→</span>
              </div>
            </div>
          </div>
        </van-tab>
        <van-tab title="评审记录">
          <div style="padding: 12px">
            <van-button v-if="order.status !== 'terminated' && order.status !== 'production'" block type="primary" style="margin-bottom: 12px" @click="handleSubmitReview">
              提交评审
            </van-button>
            <van-cell v-for="item in reviews" :key="item.id">
              <template #title>
                <span>评审 #{{ item.id }}</span>
                <van-tag :type="item.conclusion === 'approved' ? 'success' : item.conclusion === 'terminated' ? 'danger' : item.conclusion === 'pending' ? 'warning' : 'default'" style="margin-left: 6px">
                  {{ conclusionMap[item.conclusion] || item.conclusion }}
                </van-tag>
              </template>
              <template #label>
                <div>阶段: {{ item.review_stage || '-' }}</div>
                <div v-if="item.reviewed_at">评审时间: {{ item.reviewed_at?.slice(0, 19).replace('T', ' ') }}</div>
                <div>创建: {{ item.created_at?.slice(0, 19).replace('T', ' ') }}</div>
              </template>
              <template v-if="item.conclusion === 'pending'" #value>
                <van-space>
                  <van-button size="mini" type="success" @click="handleReviewDecision(item.id, 'approved')">通过</van-button>
                  <van-button size="mini" type="warning" @click="handleReviewDecision(item.id, 'adjust')">调整</van-button>
                  <van-button size="mini" type="danger" @click="handleReviewDecision(item.id, 'terminated')">终止</van-button>
                </van-space>
              </template>
            </van-cell>
            <van-empty v-if="reviews.length === 0" description="暂无评审记录" />
          </div>
        </van-tab>
      </van-tabs>
    </div>
    <div v-else style="padding: 40px; text-align: center; color: #999">试产工单不存在</div>
  </div>
</template>
