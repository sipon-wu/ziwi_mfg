<template>
  <van-popup
    v-model:show="store.drawerOpen"
    position="right"
    :style="{ width: '420px', height: '100%', maxWidth: '100%' }"
  >
    <div class="copilot-drawer">
      <!-- 头部 -->
      <div class="cd-header">
        <div class="cd-title">🤖 AI 数据助手</div>
        <div class="cd-actions">
          <span
            class="cd-tab"
            :class="{ active: store.view === 'chat' }"
            @click="store.setView('chat')"
          >
            问答
          </span>
          <span
            class="cd-tab"
            :class="{ active: store.view === 'briefing' }"
            @click="() => onShowBriefing()"
          >
            简报
          </span>
          <van-icon name="cross" class="cd-close" @click="store.toggleDrawer(false)" />
        </div>
      </div>

      <!-- 问答视图 -->
      <template v-if="store.view === 'chat'">
        <div ref="scrollEl" class="cd-body">
          <ChatMessageList :messages="store.messages" @feedback="onFeedback" />
        </div>
        <QuickAskChips @ask="onAsk" />
        <div class="cd-input">
          <input
            v-model="question"
            class="cd-input-field"
            type="text"
            placeholder="问我：昨天产量是多少…"
            :disabled="store.loading"
            @keyup.enter="onSend"
          />
          <button class="cd-send" :disabled="store.loading || !question.trim()" @click="onSend">
            发送
          </button>
        </div>
      </template>

      <!-- 简报视图 -->
      <template v-else>
        <div class="cd-briefing-roles">
          <span
            v-for="role in roles"
            :key="role"
            class="role-chip"
            :class="{ active: currentRole === role }"
            @click="onShowBriefing(role)"
          >
            {{ role }}
          </span>
        </div>
        <div class="cd-body">
          <BriefingBoard :briefing="store.briefing" :loading="store.briefingLoading" />
        </div>
      </template>
    </div>
  </van-popup>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useCopilotStore } from '@/stores/copilot'
import type { ChatMessage } from '@/types/copilot'
import BriefingBoard from './BriefingBoard.vue'
import ChatMessageList from './ChatMessageList.vue'
import QuickAskChips from './QuickAskChips.vue'

const store = useCopilotStore()
const question = ref('')
const scrollEl = ref<HTMLDivElement | null>(null)
const roles = ['厂长', '质量', '设备', '车间主任']
const currentRole = ref('厂长')

function scrollToBottom() {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

watch(() => store.messages.length, scrollToBottom)

function onSend() {
  const q = question.value.trim()
  if (!q || store.loading) return
  question.value = ''
  store.ask(q).then(scrollToBottom)
}

function onAsk(q: string) {
  store.ask(q).then(scrollToBottom)
}

function onFeedback(msg: ChatMessage, rating: 'good' | 'bad') {
  store.feedback(msg.messageId, rating)
}

function onShowBriefing(role?: string) {
  if (typeof role === 'string') currentRole.value = role
  store.setView('briefing')
  store.loadBriefing(currentRole.value)
}
</script>

<style scoped>
.copilot-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--ziwi-bg);
}
.cd-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border);
  flex-shrink: 0;
}
.cd-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ziwi-text-primary);
}
.cd-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cd-tab {
  font-size: 13px;
  color: var(--ziwi-text-muted);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: var(--ziwi-radius-sm);
}
.cd-tab.active {
  color: var(--ziwi-primary);
  background: var(--ziwi-primary-bg);
  font-weight: 600;
}
.cd-close {
  font-size: 16px;
  color: var(--ziwi-text-muted);
  cursor: pointer;
}
.cd-body {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.cd-briefing-roles {
  display: flex;
  gap: 8px;
  padding: 10px 12px 0;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.role-chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 14px;
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border);
  color: var(--ziwi-text-secondary);
  cursor: pointer;
}
.role-chip.active {
  background: var(--ziwi-primary);
  border-color: var(--ziwi-primary);
  color: #fff;
}
.cd-input {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  background: var(--ziwi-bg-white);
  border-top: 1px solid var(--ziwi-border);
  flex-shrink: 0;
}
.cd-input-field {
  flex: 1;
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-md);
  padding: 8px 10px;
  font-size: 13px;
  outline: none;
}
.cd-input-field:focus {
  border-color: var(--ziwi-primary);
}
.cd-send {
  border: none;
  background: var(--ziwi-primary);
  color: #fff;
  border-radius: var(--ziwi-radius-md);
  padding: 0 16px;
  font-size: 13px;
  cursor: pointer;
}
.cd-send:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
