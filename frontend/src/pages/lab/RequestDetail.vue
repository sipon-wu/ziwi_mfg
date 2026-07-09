<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { showToast, showConfirmDialog, showDialog } from 'vant'
import {
  getRequest, receiveSample, assignTester, startTesting,
  submitResults, approveRequest, revertStatus, getReport, publishReport,
} from '@/api/lab'
import type { LabRequest } from '@/api/lab'

const router = useRouter()
const route = useRoute()
const id = Number(route.params.id)
const request = ref<LabRequest | null>(null)
const report = ref<any>(null)
const loading = ref(false)

const statusSteps = ['pending', 'received', 'assigned', 'in_progress', 'reviewing', 'done']
const statusLabels: Record<string, string> = {
  pending: '待接收', received: '已接收', assigned: '已分派',
  in_progress: '进行中', reviewing: '审核中', done: '已完成',
}
const typeLabels: Record<string, string> = {
  mechanical: '力学性能', metallographic: '金相分析', chemical: '化学成分',
  dimensional: '尺寸测量', environmental: '环境试验', physical: '物理性能',
  aging: '老化试验', ndt: '无损检测', cleanliness: '洁净度', other: '其他',
}

const currentStep = computed(() => {
  if (!request.value) return 0
  return statusSteps.indexOf(request.value.status)
})

const statusPercent = computed(() => {
  return Math.round(((currentStep.value) / (statusSteps.length - 1)) * 100)
})

// 结果表单
const showResultsForm = ref(false)
const resultsInput = ref('[]')

// 分派表单
const showAssignForm = ref(false)
const assigneeId = ref(0)

async function fetch() {
  loading.value = true
  try {
    request.value = await getRequest(id)
  } finally { loading.value = false }
}

async function fetchReport() {
  try { report.value = await getReport(id) }
  catch { report.value = null }
}

onMounted(() => {
  fetch()
  fetchReport()
})

async function handleReceive() {
  try {
    await showConfirmDialog({ title: '接收样品', message: '确认接收该实验委托的样品？' })
    await receiveSample(id)
    showToast('样品已接收')
    fetch()
  } catch { /* cancelled */ }
}

async function handleAssign() {
  showAssignForm.value = true
}

async function doAssign() {
  if (!assigneeId.value) { showToast('请输入检测人员ID'); return }
  try {
    await assignTester(id, assigneeId.value)
    showToast('分派成功')
    showAssignForm.value = false
    fetch()
  } catch (e: any) {
    showToast(e.response?.data?.detail?.message || '分派失败')
  }
}

async function handleStart() {
  try {
    await showConfirmDialog({ title: '开始检测', message: '确认开始执行检测？' })
    await startTesting(id)
    showToast('检测已开始')
    fetch()
  } catch { /* cancelled */ }
}

async function handleSubmitResults() {
  showResultsForm.value = true
  try {
    const cur = await getRequest(id)
    resultsInput.value = cur.test_results?.length
      ? JSON.stringify(cur.test_results.map(r => ({
          item_name: r.item_name,
          spec_value: r.spec_value,
          actual_value: r.actual_value,
          unit: r.unit,
          lower_limit: r.lower_limit,
          upper_limit: r.upper_limit,
          is_pass: r.is_pass,
          remark: r.remark,
        })), null, 2)
      : '[]'
  } catch { resultsInput.value = '[]' }
}

async function doSubmitResults() {
  let results: any[]
  try {
    results = JSON.parse(resultsInput.value)
  } catch {
    showToast('JSON 格式错误')
    return
  }
  if (!results.length) { showToast('请至少输入一条检测结果'); return }
  try {
    await submitResults(id, results)
    showToast('检测结果已提交')
    showResultsForm.value = false
    fetch()
  } catch (e: any) {
    showToast(e.response?.data?.detail?.message || '提交失败')
  }
}

async function handleApprove() {
  try {
    await showConfirmDialog({ title: '审核通过', message: '确认审核通过？' })
    await approveRequest(id)
    showToast('审核通过')
    fetch()
  } catch { /* cancelled */ }
}

async function handleRevert() {
  const curStatus = request.value?.status
  const msg = curStatus === 'assigned' ? '回退到「已接收」？' :
    curStatus === 'in_progress' ? '回退到「已分派」？' :
    curStatus === 'reviewing' ? '回退到「进行中」？' : '确认回退？'
  try {
    await showConfirmDialog({ title: '状态回退', message: msg })
    await revertStatus(id)
    showToast('状态已回退')
    fetch()
  } catch { /* cancelled */ }
}

async function handlePublishReport() {
  try {
    await showConfirmDialog({ title: '发布报告', message: '确认发布实验报告？' })
    const conclusion = request.value?.conclusion || 'pass'
    await publishReport(id, conclusion)
    showToast('报告已发布')
    fetchReport()
  } catch { /* cancelled */ }
}

function showResultPass(is_pass: boolean | null): string {
  if (is_pass === null) return '待判定'
  return is_pass ? '合格' : '不合格'
}
</script>

<template>
  <div>
    <van-nav-bar title="实验委托详情" left-text="返回" @click-left="router.back()" />

    <div v-if="loading || !request" style="padding: 40px; text-align: center; color: #999">
      {{ loading ? '加载中...' : '委托不存在' }}
    </div>

    <template v-if="request">
      <!-- 进度条 -->
      <div style="padding: 16px">
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px">
          <span style="font-weight: bold">{{ request.request_no }}</span>
          <van-tag :type="request.status === 'done' ? 'success' : 'primary'">
            {{ statusLabels[request.status] }}
          </van-tag>
        </div>
        <van-progress :percentage="statusPercent" :stroke-width="8" />
        <div style="display: flex; justify-content: space-between; font-size: 11px; color: #999; margin-top: 4px">
          <span v-for="s in statusSteps" :key="s">{{ statusLabels[s] }}</span>
        </div>
      </div>

      <!-- 基础信息 -->
      <van-cell-group title="基本信息">
        <van-cell title="标题" :value="request.title" />
        <van-cell title="类型" :value="typeLabels[request.request_type] || request.request_type" />
        <van-cell title="来源" :value="request.source_type || '-'" />
        <van-cell title="优先级" :value="request.priority" />
        <van-cell title="描述" :value="request.description || '-'" />
        <van-cell title="样品信息">{{ request.sample_info ? JSON.stringify(request.sample_info) : '-' }}</van-cell>
        <van-cell title="期望完成" :value="request.expected_date?.slice(0, 10) || '-'" />
        <van-cell title="创建人" :value="String(request.created_by || '') || '-'" />
        <van-cell title="创建时间" :value="request.created_at?.slice(0, 16) || '-'" />
      </van-cell-group>

      <!-- 操作按钮 -->
      <van-cell-group title="操作">
        <div style="padding: 12px 16px">
          <van-space>
            <van-button v-if="request.status === 'pending'" type="primary" size="small" @click="handleReceive">接收样品</van-button>
            <van-button v-if="request.status === 'received'" type="primary" size="small" @click="handleAssign">分派检测</van-button>
            <van-button v-if="request.status === 'assigned'" type="primary" size="small" @click="handleStart">开始检测</van-button>
            <van-button v-if="request.status === 'in_progress'" type="primary" size="small" @click="handleSubmitResults">提交结果</van-button>
            <van-button v-if="request.status === 'reviewing'" type="success" size="small" @click="handleApprove">审核通过</van-button>
            <van-button v-if="request.status === 'done' && !report" type="primary" size="small" @click="handlePublishReport">发布报告</van-button>
            <van-button v-if="['assigned', 'in_progress', 'reviewing'].includes(request.status)" type="warning" size="small" @click="handleRevert">回退</van-button>
          </van-space>
        </div>
      </van-cell-group>

      <!-- 检测结果 -->
      <van-cell-group title="检测结果">
        <van-cell v-if="!request.test_results?.length" title="暂无检测数据" />
        <div v-else>
          <van-cell v-for="r in request.test_results" :key="r.id">
            <template #title>
              <span>{{ r.item_name }}</span>
              <van-tag
                :type="r.is_pass === null ? 'default' : r.is_pass ? 'success' : 'danger'"
                style="margin-left: 6px"
              >{{ showResultPass(r.is_pass) }}</van-tag>
            </template>
            <template #label>
              <div>标准值: {{ r.spec_value || '-' }} | 实测值: {{ r.actual_value || '-' }} {{ r.unit || '' }}</div>
              <div v-if="r.lower_limit !== null || r.upper_limit !== null">限值: {{ r.lower_limit ?? '-' }} ~ {{ r.upper_limit ?? '-' }} {{ r.unit || '' }}</div>
              <div v-if="r.remark">备注: {{ r.remark }}</div>
            </template>
          </van-cell>
        </div>
      </van-cell-group>

      <!-- 报告 -->
      <van-cell-group title="实验报告">
        <van-cell v-if="!report" title="暂无报告" />
        <template v-if="report">
          <van-cell title="报告编号" :value="report.report_no" />
          <van-cell title="结论" :value="report.conclusion" />
          <van-cell title="摘要" :value="report.summary || '-'" />
          <van-cell title="发布时间" :value="report.published_at?.slice(0, 16) || '-'" />
        </template>
      </van-cell-group>
    </template>

    <!-- 分派弹窗 -->
    <van-dialog v-model:show="showAssignForm" title="分派检测人员" show-cancel-button @confirm="doAssign">
      <van-field v-model.number="assigneeId" label="检测人员ID" type="number" placeholder="请输入人员ID" />
    </van-dialog>

    <!-- 提交结果弹窗 -->
    <van-dialog v-model:show="showResultsForm" title="提交检测结果" show-cancel-button @confirm="doSubmitResults" style="max-height: 80vh; overflow: auto">
      <van-field
        v-model="resultsInput"
        type="textarea"
        rows="10"
        placeholder='[{"item_name":"拉伸强度","spec_value":"≥800","actual_value":"815","unit":"MPa","lower_limit":600,"upper_limit":1000}]'
        autosize
      />
    </van-dialog>
  </div>
</template>

<script lang="ts">
export default { name: 'LabRequestDetail' }
</script>
