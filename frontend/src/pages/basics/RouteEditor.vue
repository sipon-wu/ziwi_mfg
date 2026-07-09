<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showDialog } from 'vant'
import { get, put } from '@/api/client'

const route = useRoute()
const router = useRouter()
const routeId = Number(route.params.id)

interface RouteInfo {
  id: number
  code: string
  name: string
  version: number
  status: string
  route_type: string
  description: string | null
}

interface OperationOption {
  id: number
  code: string
  name: string
  op_type: string
  setup_time: number
  unit_time: number
}

interface WorkCenterOption {
  id: number
  code: string
  name: string
  wc_type: string
}

interface StepItem {
  id?: number
  route_id: number
  operation_id: number | null
  step_name: string
  step_seq: number
  step_type: string
  wc_id: number | null
  setup_time_override: number | null
  unit_time_override: number | null
  is_parallel_eligible: boolean
  is_outsource: boolean
  next_step_seq: number | null
  parallel_group: string | null
  remark: string | null
  // 冗余显示字段
  op_code?: string
  op_name?: string
  op_type?: string
  wc_name?: string
}

// ── State ──

const routeInfo = ref<RouteInfo | null>(null)
const steps = ref<StepItem[]>([])
const allOperations = ref<OperationOption[]>([])
const allWorkCenters = ref<WorkCenterOption[]>([])
const loading = ref(true)
const saving = ref(false)
const isDraft = computed(() => routeInfo.value?.status === 'draft')
const availableOps = computed(() => allOperations.value.filter(o => o.is_active !== false))
const selectedTab = ref('steps')

// ── 弹窗状态 ──
const showAddStep = ref(false)
const showStepDetail = ref(false)
const editingStep = ref<Partial<StepItem>>({})
const editingStepIndex = ref(-1)
const isNewStep = ref(true)

// ── 步骤类型选项 ──
const STEP_TYPE_OPTIONS = [
  { value: 'production', label: '生产' },
  { value: 'inspect', label: '检验' },
  { value: 'outsource', label: '外协' },
]

// ── 加载数据 ──

async function loadRoute() {
  try {
    const res = await get(`/api/v1/routes/${routeId}`)
    routeInfo.value = res.data
  } catch (e: any) {
    showToast('加载路线信息失败')
    router.push('/basics/routes')
  }
}

async function loadSteps() {
  try {
    const res = await get(`/api/v1/routes/${routeId}/steps`)
    steps.value = res.data || []
  } catch (e: any) {
    showToast('加载步骤失败')
  }
}

async function loadOperations() {
  try {
    const res = await get('/api/v1/operations', { params: { page_size: 500 } })
    allOperations.value = res.data.items || []
  } catch (_) { /* ignore */ }
}

async function loadWorkCenters() {
  try {
    const res = await get('/api/v1/work-centers', { params: { page_size: 500 } })
    allWorkCenters.value = res.data.items || []
  } catch (_) { /* ignore */ }
}

async function init() {
  loading.value = true
  await Promise.all([loadRoute(), loadSteps(), loadOperations(), loadWorkCenters()])
  loading.value = false
}

onMounted(init)

// ── 步骤操作 ──

function getOpLabel(opId: number | null): string {
  if (!opId) return ''
  const op = allOperations.value.find(o => o.id === opId)
  return op ? `${op.code} - ${op.name}` : ''
}

function getWcLabel(wcId: number | null): string {
  if (!wcId) return ''
  const wc = allWorkCenters.value.find(w => w.id === wcId)
  return wc ? `${wc.code}` : ''
}

function openAddStep() {
  isNewStep.value = true
  editingStep.value = {
    route_id: routeId,
    operation_id: null,
    step_name: '',
    step_seq: steps.value.length + 1,
    step_type: 'production',
    wc_id: null,
    setup_time_override: null,
    unit_time_override: null,
    is_parallel_eligible: false,
    is_outsource: false,
    next_step_seq: null,
    parallel_group: null,
    remark: null,
  }
  showAddStep.value = true
}

function openEditStep(index: number) {
  isNewStep.value = false
  editingStepIndex.value = index
  editingStep.value = { ...steps.value[index] }
  showStepDetail.value = true
}

function confirmAddStep() {
  if (!editingStep.value.operation_id) {
    showToast('请选择工序')
    return
  }
  if (isNewStep.value) {
    editingStep.value.step_seq = steps.value.length + 1
    // 补齐显示字段
    const op = allOperations.value.find(o => o.id === editingStep.value.operation_id)
    if (op) {
      editingStep.value.op_code = op.code
      editingStep.value.op_name = op.name
      editingStep.value.op_type = op.op_type
    }
    const wc = allWorkCenters.value.find(w => w.id === editingStep.value.wc_id)
    if (wc) editingStep.value.wc_name = wc.name
    steps.value.push(editingStep.value as StepItem)
  } else {
    const op = allOperations.value.find(o => o.id === editingStep.value.operation_id)
    if (op) {
      editingStep.value.op_code = op.code
      editingStep.value.op_name = op.name
      editingStep.value.op_type = op.op_type
    }
    const wc = allWorkCenters.value.find(w => w.id === editingStep.value.wc_id)
    if (wc) editingStep.value.wc_name = wc.name
    steps.value[editingStepIndex.value] = editingStep.value as StepItem
  }
  showAddStep.value = false
  showStepDetail.value = false
  recalcSeq()
}

function removeStep(index: number) {
  steps.value.splice(index, 1)
  recalcSeq()
}

function moveStep(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= steps.value.length) return
  const tmp = steps.value[index]
  steps.value[index] = steps.value[target]
  steps.value[target] = tmp
  recalcSeq()
}

function recalcSeq() {
  steps.value.forEach((s, i) => {
    s.step_seq = i + 1
    if (i < steps.value.length - 1) {
      s.next_step_seq = i + 2
    } else {
      s.next_step_seq = null
    }
  })
}

// ── 保存步骤 ──

async function saveSteps() {
  if (steps.value.length === 0) {
    showToast('请至少添加一个工序')
    return
  }
  saving.value = true
  try {
    recalcSeq()
    const payload = steps.value.map(s => ({
      route_id: routeId,
      operation_id: s.operation_id,
      step_name: s.step_name,
      step_seq: s.step_seq,
      step_type: s.step_type,
      wc_id: s.wc_id,
      setup_time_override: s.setup_time_override,
      unit_time_override: s.unit_time_override,
      is_parallel_eligible: s.is_parallel_eligible,
      is_outsource: s.step_type === 'outsource',
      next_step_seq: s.next_step_seq,
      parallel_group: s.parallel_group,
      remark: s.remark,
    }))
    await put(`/api/v1/routes/${routeId}/steps`, payload)
    showToast('步骤保存成功')
  } catch (e: any) {
    showToast(e?.detail?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

// ── 工作中心类型色标 ──
function wcTypeLabel(t: string): string {
  const map: Record<string, string> = {
    production_line: '产线',
    work_cell: '单元',
    workstation: '工位',
  }
  return map[t] || t
}
</script>

<template>
  <div class="p-4">
    <!-- 返回按钮 -->
    <div class="flex items-center gap-3 mb-4">
      <van-button icon="arrow-left" plain size="small" @click="router.push('/basics/routes')"/>
      <div>
        <div class="text-base font-medium">
          {{ routeInfo?.code }} V{{ routeInfo?.version }} - {{ routeInfo?.name }}
        </div>
        <div class="text-xs text-gray-400">
          状态: {{ routeInfo?.status }} | 工序数: {{ steps.length }}
          <van-tag v-if="!isDraft" type="warning" size="small" class="ml-1">只读</van-tag>
        </div>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="text-center py-8 text-gray-400">加载中...</div>

    <template v-if="!loading">
      <!-- 操作区 -->
      <div class="flex gap-2 mb-4 flex-wrap" v-if="isDraft">
        <van-button type="primary" size="small" icon="plus" @click="openAddStep">添加工序</van-button>
        <van-button type="success" size="small" icon="success" :loading="saving" @click="saveSteps">保存编排</van-button>
      </div>

      <!-- 工序编排列表 -->
      <div class="space-y-2">
        <div
          v-for="(step, index) in steps"
          :key="step.step_seq"
          class="border rounded-lg p-3 bg-white shadow-sm"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-full bg-blue-500 text-white flex items-center justify-center text-xs font-bold">
                {{ step.step_seq }}
              </div>
              <div>
                <div class="font-medium">
                  {{ step.op_code || '' }}
                  <span class="text-gray-500 ml-1">{{ step.op_name || '' }}</span>
                </div>
                <div class="text-xs text-gray-400 flex gap-2 mt-0.5">
                  <van-tag plain size="mini">{{ step.step_type === 'outsource' ? '外协' : step.step_type === 'inspect' ? '检验' : '生产' }}</van-tag>
                  <span v-if="step.wc_id">工作中心: {{ getWcLabel(step.wc_id) }}</span>
                  <span v-if="step.parallel_group">并行组: {{ step.parallel_group }}</span>
                </div>
                <div v-if="step.setup_time_override || step.unit_time_override" class="text-xs text-gray-400 mt-0.5">
                  准备: {{ step.setup_time_override }}min | 单件: {{ step.unit_time_override }}min
                </div>
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="flex gap-1 flex-shrink-0" v-if="isDraft">
              <van-button icon="arrow-up" size="small" plain @click="moveStep(index, -1)" :disabled="index === 0" />
              <van-button icon="arrow-down" size="small" plain @click="moveStep(index, 1)" :disabled="index === steps.length - 1" />
              <van-button icon="edit" size="small" type="primary" plain @click="openEditStep(index)" />
              <van-button icon="delete" size="small" type="danger" plain @click="removeStep(index)" />
            </div>
          </div>
        </div>

        <div v-if="steps.length === 0" class="text-center py-10 text-gray-400 border rounded-lg bg-white">
          <div class="text-4xl mb-2">+</div>
          <div>暂无工序，请点击「添加工序」开始编排</div>
        </div>
      </div>
    </template>

    <!-- ── 添加/编辑工序弹窗 ── -->
    <van-dialog
      v-model:show="showAddStep || showStepDetail"
      :title="isNewStep ? '添加工序' : '编辑工序'"
      show-cancel-button
      @confirm="confirmAddStep"
      class="!w-[520px]"
    >
      <div class="p-4 space-y-3 max-h-[70vh] overflow-y-auto">
        <van-field label="选择工序" required>
          <template #input>
            <van-select v-model="editingStep.operation_id" placeholder="请选择工序">
              <van-option
                v-for="op in availableOps"
                :key="op.id"
                :value="op.id"
                :label="`${op.code} - ${op.name}`"
              />
            </van-select>
          </template>
        </van-field>

        <van-field v-model="editingStep.step_name" label="步骤名称" placeholder="留空则使用工序名称" />

        <van-field label="步骤类型">
          <template #input>
            <van-select v-model="editingStep.step_type" class="w-full">
              <van-option v-for="opt in STEP_TYPE_OPTIONS" :key="opt.value" :value="opt.value" :label="opt.label" />
            </van-select>
          </template>
        </van-field>

        <van-field label="执行工作中心">
          <template #input>
            <van-select v-model="editingStep.wc_id" placeholder="可选" clearable>
              <van-option
                v-for="wc in allWorkCenters"
                :key="wc.id"
                :value="wc.id"
                :label="`${wc.code} - ${wc.name}`"
              />
            </van-select>
          </template>
        </van-field>

        <div class="flex gap-2">
          <van-field v-model.number="editingStep.setup_time_override" label="准备时间(min)" type="number" placeholder="继承工序" />
          <van-field v-model.number="editingStep.unit_time_override" label="单件时间(min)" type="number" placeholder="继承工序" />
        </div>

        <van-field label="并行组标识" placeholder="可选，同组可并行">
          <template #input>
            <van-field v-model="editingStep.parallel_group" placeholder="例如: P1, P2" style="border: none; padding: 0;" />
          </template>
        </van-field>

        <van-field label="允许并行">
          <template #input>
            <van-switch v-model="editingStep.is_parallel_eligible" />
          </template>
        </van-field>

        <van-field v-model="editingStep.remark" label="备注" type="textarea" rows="2" placeholder="可选" />
      </div>
    </van-dialog>
  </div>
</template>
