<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

interface ControlLimit {
  id: number
  chart_type: string
  dimension_key: string
  cl: number
  ucl: number
  lcl: number
  usl: number | null
  lsl: number | null
  mode: string
  subgroup_count: number
  calculated_at: string | null
  created_at: string
  updated_at: string
}

const router = useRouter()
const list = ref<ControlLimit[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const chartTypeFilter = ref('')
const showDialog_ = ref(false)
const editingItem = ref<ControlLimit | null>(null)
const form = ref({
  chart_type: 'xbar_r',
  dimension_key: '',
  cl: 0,
  ucl: 0,
  lcl: 0,
  usl: null as number | null,
  lsl: null as number | null,
  mode: 'manual',
})
const submitting = ref(false)

const chartTypeOptions = [
  { value: 'xbar_r', label: 'X̄-R' },
  { value: 'xbar_s', label: 'X̄-S' },
  { value: 'p', label: 'p' },
  { value: 'np', label: 'np' },
]

const modeOptions = [
  { value: 'manual', label: '手动' },
  { value: 'auto', label: '自动' },
]

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (chartTypeFilter.value) params.chart_type = chartTypeFilter.value

  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<ControlLimit>>('/spc/control-limits', { ...params, ...p })
  })
  list.value = (items as unknown) as ControlLimit[]
}

function onChartTypeChange() {
  resetPage()
  loadData()
}

function openCreate() {
  editingItem.value = null
  form.value = {
    chart_type: 'xbar_r',
    dimension_key: '',
    cl: 0,
    ucl: 0,
    lcl: 0,
    usl: null,
    lsl: null,
    mode: 'manual',
  }
  showDialog_.value = true
}

function openEdit(item: ControlLimit) {
  editingItem.value = item
  form.value = {
    chart_type: item.chart_type,
    dimension_key: item.dimension_key,
    cl: item.cl,
    ucl: item.ucl,
    lcl: item.lcl,
    usl: item.usl,
    lsl: item.lsl,
    mode: item.mode,
  }
  showDialog_.value = true
}

async function handleSave() {
  if (!form.value.dimension_key) {
    showToast('请输入维度标识')
    return
  }
  submitting.value = true
  try {
    if (editingItem.value) {
      await put(`/spc/control-limits/${editingItem.value.id}`, form.value)
      showToast('更新成功')
    } else {
      await post('/spc/control-limits', form.value)
      showToast('创建成功')
    }
    showDialog_.value = false
    loadData()
  } catch {
    showToast(editingItem.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(item: ControlLimit) {
  try {
    await showConfirmDialog({ message: '确定删除该控制限配置？' })
    await del(`/spc/control-limits/${item.id}`)
    showToast('删除成功')
    loadData()
  } catch {
    // cancelled
  }
}

function goChart(item: ControlLimit) {
  router.push(`/quality/spc/control-limits/${item.id}/chart`)
}

function goCapability(item: ControlLimit) {
  router.push(`/quality/spc/control-limits/${item.id}/capability`)
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="SPC控制限配置" right-text="新建配置" @click-right="openCreate" />

    <div style="display:flex; gap:8px; margin:12px; flex-wrap:wrap;">
      <van-tag
        v-for="opt in chartTypeOptions" :key="opt.value"
        :type="chartTypeFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="chartTypeFilter = chartTypeFilter === opt.value ? '' : opt.value; onChartTypeChange()"
      >{{ opt.label }}</van-tag>
    </div>

    <van-list v-model:loading="loading" :finished="!total || list.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          <span>{{ item.dimension_key }}</span>
          <van-tag style="margin-left:6px" :type="item.mode === 'auto' ? 'warning' : 'primary'">
            {{ item.mode === 'auto' ? '自动' : '手动' }}
          </van-tag>
          <van-tag style="margin-left:4px" plain>{{ item.chart_type }}</van-tag>
        </template>
        <template #label>
          <div>CL={{ item.cl.toFixed(2) }} UCL={{ item.ucl.toFixed(2) }} LCL={{ item.lcl.toFixed(2) }}</div>
          <div v-if="item.usl !== null">USL={{ item.usl }} LSL={{ item.lsl }}</div>
          <div>子组数: {{ item.subgroup_count }}</div>
        </template>
        <template #value>
          <div style="display:flex; gap:4px; flex-wrap:wrap">
            <van-button size="mini" plain type="primary" @click="goChart(item)">控制图</van-button>
            <van-button size="mini" plain type="success" @click="goCapability(item)">能力分析</van-button>
            <van-button size="mini" plain type="warning" @click="openEdit(item)">编辑</van-button>
            <van-button size="mini" plain type="danger" @click="handleDelete(item)">删除</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && list.length === 0" description="暂无控制限配置" />

    <!-- 创建/编辑弹窗 -->
    <van-dialog v-model:show="showDialog_" :title="editingItem ? '编辑控制限' : '新建控制限'" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleSave(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model="form.dimension_key" label="维度标识" placeholder="如 product_1_process_1" :rules="[{ required: true }]" />
        <van-field name="chart_type" label="控制图类型">
          <template #input>
            <van-radio-group v-model="form.chart_type" direction="horizontal">
              <van-radio v-for="t in chartTypeOptions" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field v-model.number="form.cl" label="中心线(CL)" type="digit" />
        <van-field v-model.number="form.ucl" label="上控制限(UCL)" type="digit" />
        <van-field v-model.number="form.lcl" label="下控制限(LCL)" type="digit" />
        <van-field :model-value="form.usl ?? ''" label="规格上限(USL)" type="digit" placeholder="选填" @update:model-value="form.usl = $event ? Number($event) : null" />
        <van-field :model-value="form.lsl ?? ''" label="规格下限(LSL)" type="digit" placeholder="选填" @update:model-value="form.lsl = $event ? Number($event) : null" />
        <van-field name="mode" label="控制模式">
          <template #input>
            <van-radio-group v-model="form.mode" direction="horizontal">
              <van-radio v-for="m in modeOptions" :key="m.value" :name="m.value">{{ m.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
      </div>
    </van-dialog>
  </div>
</template>
