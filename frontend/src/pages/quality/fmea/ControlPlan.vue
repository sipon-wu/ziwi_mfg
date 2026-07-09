<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post, put } from '@/api/client'

interface ControlPlanItem {
  id: number
  fmea_doc_id: number
  fmea_item_id: number
  process_id: number | null
  control_item: string
  control_method: string
  frequency: string | null
  responsible: string | null
  specification: string | null
  source: string
  status: string
  created_at: string
  updated_at: string
}

interface DocInfo {
  id: number
  title: string
  doc_no: string
}

const route = useRoute()
const router = useRouter()
const docId = Number(route.params.id)
const docInfo = ref<DocInfo | null>(null)
const loading = ref(false)
const plans = ref<ControlPlanItem[]>([])
const generating = ref(false)
const editingId = ref<number | null>(null)
const editForm = ref({
  control_item: '',
  control_method: '',
  frequency: '',
  responsible: '',
  specification: '',
  status: 'draft',
})
const showEditDialog = ref(false)
const submitting = ref(false)

const statusMap: Record<string, string> = {
  draft: '草稿',
  active: '已启用',
  archived: '已归档',
}

async function fetchData() {
  loading.value = true
  try {
    docInfo.value = await get<DocInfo>(`/fmea/documents/${docId}`)
    const res = await get<{ items: ControlPlanItem[]; total: number }>('/fmea/control-plans', {
      fmea_doc_id: docId,
      page_size: 500,
    })
    plans.value = res.items || []
  } catch (e) {
    showToast('加载控制计划失败')
    console.warn('[ControlPlan]', e)
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    const res = await post<{ count: number }>('/fmea/control-plans/generate', {
      fmea_doc_id: docId,
    })
    showToast(`已生成 ${res.count} 条控制计划`)
    fetchData()
  } catch {
    showToast('生成失败')
  } finally {
    generating.value = false
  }
}

function openEdit(plan: ControlPlanItem) {
  editingId.value = plan.id
  editForm.value = {
    control_item: plan.control_item,
    control_method: plan.control_method,
    frequency: plan.frequency || '',
    responsible: plan.responsible || '',
    specification: plan.specification || '',
    status: plan.status,
  }
  showEditDialog.value = true
}

async function handleSave() {
  if (!editingId.value) return
  submitting.value = true
  try {
    await put(`/fmea/control-plans/${editingId.value}`, editForm.value)
    showToast('更新成功')
    showEditDialog.value = false
    fetchData()
  } catch {
    showToast('更新失败')
  } finally {
    submitting.value = false
  }
}

onMounted(fetchData)
</script>

<template>
  <div>
    <van-nav-bar title="控制计划" left-arrow @click-left="router.back()">
      <template #right>
        <van-button size="mini" :loading="generating" type="primary" @click="handleGenerate">从FMEA生成</van-button>
      </template>
    </van-nav-bar>

    <van-loading v-if="loading" />

    <div v-else>
      <!-- 文档信息 -->
      <van-cell-group v-if="docInfo" title="文档信息">
        <van-cell title="文档" :value="docInfo.title" />
        <van-cell title="文档号" :value="docInfo.doc_no" />
      </van-cell-group>

      <!-- 控制计划列表 -->
      <van-cell-group title="控制项">
        <van-cell v-for="plan in plans" :key="plan.id">
          <template #title>
            {{ plan.control_item }}
            <van-tag
              :type="plan.status === 'active' ? 'success' : plan.status === 'archived' ? 'default' : 'warning'"
              style="margin-left:6px"
            >{{ statusMap[plan.status] || plan.status }}</van-tag>
            <van-tag v-if="plan.source === 'auto'" plain style="margin-left:4px" type="primary">自动生成</van-tag>
          </template>
          <template #label>
            <div>控制方法: {{ plan.control_method }}</div>
            <div v-if="plan.frequency">频次: {{ plan.frequency }}</div>
            <div v-if="plan.responsible">责任人: {{ plan.responsible }}</div>
            <div v-if="plan.specification">规格: {{ plan.specification }}</div>
          </template>
          <template #value>
            <van-button size="mini" plain type="primary" @click="openEdit(plan)">编辑</van-button>
          </template>
        </van-cell>
      </van-cell-group>

      <van-empty v-if="!plans.length" description="暂无控制计划，点击右上角从FMEA生成" />
    </div>

    <!-- 编辑控制计划弹窗 -->
    <van-dialog v-model:show="showEditDialog" title="编辑控制项" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleSave(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model="editForm.control_item" label="控制项" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="editForm.control_method" label="控制方法" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="editForm.frequency" label="频次" placeholder="如：每班次" />
        <van-field v-model="editForm.responsible" label="责任人" placeholder="选填" />
        <van-field v-model="editForm.specification" label="规格要求" placeholder="选填" />
        <van-field name="status" label="状态">
          <template #input>
            <van-radio-group v-model="editForm.status" direction="horizontal">
              <van-radio name="draft">草稿</van-radio>
              <van-radio name="active">启用</van-radio>
              <van-radio name="archived">归档</van-radio>
            </van-radio-group>
          </template>
        </van-field>
      </div>
    </van-dialog>
  </div>
</template>
