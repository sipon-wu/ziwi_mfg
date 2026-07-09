<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put } from '@/api/client'

interface FmeaAction {
  id: number
  item_id: number
  action_desc: string
  responsible_id: number
  target_date: string | null
  status: string
  completed_at: string | null
  re_severity: number | null
  re_occurrence: number | null
  re_detection: number | null
  re_rpn: number | null
  remark: string | null
  created_at: string
  updated_at: string
}

interface FmeaItem {
  id: number
  function_desc: string
  failure_mode: string
  severity: number
  occurrence: number
  detection: number
  rpn: number
}

const route = useRoute()
const router = useRouter()
const docId = Number(route.params.id)
const loading = ref(false)
const actions = ref<FmeaAction[]>([])
const fmeaItems = ref<FmeaItem[]>([])
const showCreateDialog = ref(false)
const showCompleteDialog = ref(false)
const selectedAction = ref<FmeaAction | null>(null)
const form = ref({
  item_id: 0,
  action_desc: '',
  responsible_id: 0,
  target_date: '',
  remark: '',
})
const completeForm = ref({
  re_severity: 1,
  re_occurrence: 1,
  re_detection: 1,
})
const submitting = ref(false)

const statusMap: Record<string, string> = {
  open: '待处理',
  in_progress: '进行中',
  completed: '已完成',
  closed: '已关闭',
}

async function fetchData() {
  loading.value = true
  try {
    // Get all FMEA items for this doc
    const itemsRes = await get<{ items: FmeaItem[]; total: number }>('/fmea/items', { doc_id: docId, page_size: 500 })
    fmeaItems.value = itemsRes.items || []

    // Get all actions from each item
    const allActions: FmeaAction[] = []
    for (const item of fmeaItems.value) {
      try {
        const itemActions = await get<FmeaAction[]>(`/fmea/items/${item.id}/actions`)
        if (Array.isArray(itemActions)) {
          allActions.push(...itemActions.map(a => ({ ...a, _function_desc: item.function_desc, _failure_mode: item.failure_mode })))
        }
      } catch {
        // skip items without actions
      }
    }
    actions.value = allActions
  } catch (e) {
    showToast('加载整改措施数据失败')
    console.warn('[FmeaActions]', e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = {
    item_id: fmeaItems.value[0]?.id || 0,
    action_desc: '',
    responsible_id: 0,
    target_date: '',
    remark: '',
  }
  showCreateDialog.value = true
}

async function handleCreate() {
  if (!form.value.action_desc) {
    showToast('请填写措施描述')
    return
  }
  if (!form.value.item_id) {
    showToast('请选择关联的FMEA项')
    return
  }
  submitting.value = true
  try {
    await post(`/fmea/items/${form.value.item_id}/actions`, form.value)
    showToast('创建成功')
    showCreateDialog.value = false
    fetchData()
  } catch {
    showToast('创建失败')
  } finally {
    submitting.value = false
  }
}

function openComplete(action: FmeaAction) {
  selectedAction.value = action
  completeForm.value = {
    re_severity: 1,
    re_occurrence: 1,
    re_detection: 1,
  }
  showCompleteDialog.value = true
}

async function handleComplete() {
  if (!selectedAction.value) return
  submitting.value = true
  try {
    await put(`/fmea/actions/${selectedAction.value.id}/complete`, completeForm.value)
    showToast('措施已完成，RPN已重算')
    showCompleteDialog.value = false
    fetchData()
  } catch {
    showToast('操作失败')
  } finally {
    submitting.value = false
  }
}

function getItemLabel(itemId: number): string {
  const item = fmeaItems.value.find(i => i.id === itemId)
  return item ? `${item.function_desc} (RPN=${item.rpn})` : `项#${itemId}`
}

onMounted(fetchData)
</script>

<template>
  <div>
    <van-nav-bar title="FMEA整改措施" left-arrow @click-left="router.back()" right-text="新建措施" @click-right="openCreate" />

    <van-loading v-if="loading" />

    <div v-else>
      <!-- 统计卡片 -->
      <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:12px;">
        <div style="text-align:center; padding:8px; background:#fff; border-radius:8px;">
          <div style="font-size:24px; font-weight:bold; color:var(--van-primary-color)">{{ actions.filter(a => a.status === 'open').length }}</div>
          <div style="font-size:12px; color:var(--van-text-color-2)">待处理</div>
        </div>
        <div style="text-align:center; padding:8px; background:#fff; border-radius:8px;">
          <div style="font-size:24px; font-weight:bold; color:var(--van-warning-color)">{{ actions.filter(a => a.status === 'in_progress').length }}</div>
          <div style="font-size:12px; color:var(--van-text-color-2)">进行中</div>
        </div>
        <div style="text-align:center; padding:8px; background:#fff; border-radius:8px;">
          <div style="font-size:24px; font-weight:bold; color:var(--van-success-color)">{{ actions.filter(a => a.status === 'completed').length }}</div>
          <div style="font-size:12px; color:var(--van-text-color-2)">已完成</div>
        </div>
      </div>

      <van-list>
        <van-cell v-for="action in actions" :key="action.id">
          <template #title>
            <span>{{ action.action_desc }}</span>
            <van-tag
              :type="action.status === 'completed' ? 'success' : action.status === 'in_progress' ? 'warning' : 'default'"
              style="margin-left:6px"
            >{{ statusMap[action.status] || action.status }}</van-tag>
          </template>
          <template #label>
            <div>关联FMEA项: {{ getItemLabel(action.item_id) }}</div>
            <div v-if="action.target_date">目标日期: {{ action.target_date }}</div>
            <div v-if="action.re_rpn !== null">复评RPN: {{ action.re_rpn }} (S={{ action.re_severity }} O={{ action.re_occurrence }} D={{ action.re_detection }})</div>
            <div v-if="action.remark">备注: {{ action.remark }}</div>
          </template>
          <template #value>
            <van-button v-if="action.status !== 'completed'" size="mini" plain type="success" @click="openComplete(action)">完成</van-button>
          </template>
        </van-cell>
      </van-list>

      <van-empty v-if="!actions.length" description="暂无整改措施" />
    </div>

    <!-- 新建措施弹窗 -->
    <van-dialog v-model:show="showCreateDialog" title="新建整改措施" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleCreate(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field name="item_id" label="关联FMEA项">
          <template #input>
            <van-picker
              :columns="fmeaItems.map(i => ({ text: `${i.function_desc} (RPN=${i.rpn})`, value: i.id }))"
              @confirm="(v:any) => form.item_id = v.value"
            />
          </template>
        </van-field>
        <van-field v-model="form.action_desc" label="措施描述" type="textarea" rows="2" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model.number="form.responsible_id" label="责任人ID" type="digit" placeholder="选填" />
        <van-field v-model="form.target_date" label="目标完成日期" type="date" />
        <van-field v-model="form.remark" label="备注" type="textarea" rows="2" placeholder="选填" />
      </div>
    </van-dialog>

    <!-- 完成措施弹窗 -->
    <van-dialog v-model:show="showCompleteDialog" title="完成措施 - 复评" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleComplete(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model.number="completeForm.re_severity" label="复评严重度(S)" type="digit" placeholder="1-10" />
        <van-field v-model.number="completeForm.re_occurrence" label="复评频度(O)" type="digit" placeholder="1-10" />
        <van-field v-model.number="completeForm.re_detection" label="复评探测度(D)" type="digit" placeholder="1-10" />
        <van-cell title="复评RPN" :value="completeForm.re_severity * completeForm.re_occurrence * completeForm.re_detection" />
      </div>
    </van-dialog>
  </div>
</template>
