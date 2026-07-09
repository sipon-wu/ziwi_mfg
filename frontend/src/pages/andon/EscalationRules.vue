<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

interface EscalationRule {
  id: number
  rule_name: string
  call_type: string
  priority: string
  level: number
  timeout_minutes: number
  notify_role: string
  notify_users: string
  notify_channels: string
  is_active: boolean
  created_at: string
  updated_at: string
}

const list = ref<EscalationRule[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const showDialog_ = ref(false)
const editingItem = ref<EscalationRule | null>(null)
const form = ref({
  rule_name: '',
  call_type: 'quality',
  priority: 'all',
  level: 1,
  timeout_minutes: 30,
  notify_role: '',
  notify_users: '',
  notify_channels: 'app,message',
  is_active: true,
})
const channelList = ref<string[]>(['app', 'message'])
const submitting = ref(false)

const callTypeOptions = [
  { value: 'quality', label: '质量' },
  { value: 'equipment', label: '设备' },
  { value: 'production', label: '生产' },
  { value: 'other', label: '其他' },
]

const channelOptions = [
  { value: 'app', label: 'App推送' },
  { value: 'message', label: '站内信' },
  { value: 'sms', label: '短信' },
  { value: 'email', label: '邮件' },
]

async function loadData() {
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<EscalationRule>>('/andon/escalation-rules', { ...p })
  })
  list.value = (items as unknown) as EscalationRule[]
}

function openCreate() {
  editingItem.value = null
  form.value = {
    rule_name: '',
    call_type: 'quality',
    priority: 'all',
    level: 1,
    timeout_minutes: 30,
    notify_role: '',
    notify_users: '',
    notify_channels: 'app,message',
    is_active: true,
  }
  channelList.value = ['app', 'message']
  showDialog_.value = true
}

function openEdit(item: EscalationRule) {
  editingItem.value = item
  form.value = {
    rule_name: item.rule_name,
    call_type: item.call_type,
    priority: item.priority,
    level: item.level,
    timeout_minutes: item.timeout_minutes,
    notify_role: item.notify_role || '',
    notify_users: item.notify_users || '',
    notify_channels: item.notify_channels || 'app,message',
    is_active: item.is_active,
  }
  channelList.value = (item.notify_channels || 'app,message').split(',').filter(Boolean)
  showDialog_.value = true
}

async function handleSave() {
  if (!form.value.rule_name) {
    showToast('请输入规则名称')
    return
  }
  form.value.notify_channels = channelList.value.join(',')
  submitting.value = true
  try {
    if (editingItem.value) {
      await put(`/andon/escalation-rules/${editingItem.value.id}`, form.value)
      showToast('更新成功')
    } else {
      await post('/andon/escalation-rules', form.value)
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

async function handleDelete(item: EscalationRule) {
  try {
    await showConfirmDialog({ message: `确定删除规则「${item.rule_name}」？` })
    await del(`/andon/escalation-rules/${item.id}`)
    showToast('删除成功')
    loadData()
  } catch {
    // cancelled
  }
}

async function toggleActive(item: EscalationRule) {
  try {
    await put(`/andon/escalation-rules/${item.id}`, { is_active: !item.is_active })
    item.is_active = !item.is_active
    showToast(item.is_active ? '已启用' : '已禁用')
  } catch {
    showToast('操作失败')
  }
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="升级规则配置" right-text="新增规则" @click-right="openCreate" />

    <van-list v-model:loading="loading" :finished="!total || list.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          <span>{{ item.rule_name }}</span>
          <van-tag :type="item.is_active ? 'success' : 'default'" style="margin-left:8px">
            {{ item.is_active ? '启用' : '禁用' }}
          </van-tag>
        </template>
        <template #label>
          <div>级别 {{ item.level }} | 超时 {{ item.timeout_minutes }}分钟</div>
          <div>类型: {{ item.call_type }} | 通道: {{ item.notify_channels }}</div>
          <div v-if="item.notify_role">通知角色: {{ item.notify_role }}</div>
        </template>
        <template #value>
          <div style="display:flex; gap:4px; align-items:center">
            <van-switch :model-value="item.is_active" size="20" @change="toggleActive(item)" />
            <van-button size="mini" plain type="primary" @click="openEdit(item)">编辑</van-button>
            <van-button size="mini" plain type="danger" @click="handleDelete(item)">删除</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && list.length === 0" description="暂无升级规则" />

    <!-- 创建/编辑弹窗 -->
    <van-dialog v-model:show="showDialog_" :title="editingItem ? '编辑规则' : '新增规则'" show-cancel-button
      :before-close="async (action: string) => {
        if (action === 'confirm') { await handleSave(); return false }
        return true
      }">
      <div style="padding:16px">
        <van-field v-model="form.rule_name" label="规则名称" placeholder="必填" :rules="[{ required: true }]" />
        <van-field name="call_type" label="呼叫类型">
          <template #input>
            <van-radio-group v-model="form.call_type" direction="horizontal">
              <van-radio v-for="t in callTypeOptions" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field v-model.number="form.level" label="升级级别" type="digit" placeholder="1" />
        <van-field v-model.number="form.timeout_minutes" label="超时分钟数" type="digit" placeholder="30" />
        <van-field v-model="form.notify_role" label="通知角色" placeholder="如：supervisor" />
        <van-field v-model="form.notify_users" label="通知用户" placeholder="用户ID，逗号分隔" />
        <van-field name="notify_channels" label="通知通道">
          <template #input>
            <van-checkbox-group v-model="channelList" direction="horizontal">
              <van-checkbox v-for="ch in channelOptions" :key="ch.value" :name="ch.value" shape="square">{{ ch.label }}</van-checkbox>
            </van-checkbox-group>
          </template>
        </van-field>
      </div>
    </van-dialog>
  </div>
</template>
