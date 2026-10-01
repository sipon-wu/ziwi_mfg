<template>
  <div class="message-list">
    <div v-if="!messages.length" class="ml-empty">
      <div class="ml-empty-emoji">🤖</div>
      <div class="ml-empty-text">你好，我是知微 AI 制造数据助手</div>
      <div class="ml-empty-sub">可以问我产量、良率、工单、不良、安灯、设备等数据（当前为只读查询）</div>
    </div>

    <div
      v-for="msg in messages"
      :key="msg.id"
      class="msg"
      :class="msg.role === 'user' ? 'msg-user' : 'msg-assistant'"
    >
      <div v-if="msg.role === 'user'" class="bubble bubble-user">{{ msg.question }}</div>

      <div v-else class="bubble bubble-assistant">
        <div v-if="msg.loading" class="loading">
          <van-loading size="16" /> <span class="loading-text">正在分析…</span>
        </div>

        <template v-else>
          <div
            v-if="msg.eventType === 'reject' || msg.eventType === 'clarify' || msg.eventType === 'error'"
            class="notice"
            :class="`notice-${msg.eventType}`"
          >
            {{ msg.message }}
          </div>

          <AnswerCard v-if="msg.payload && msg.eventType === 'answer'" :payload="msg.payload" />

          <FeedbackBar
            v-if="msg.eventType === 'answer' && msg.payload?.answered"
            :disabled="!msg.messageId"
            @feedback="(r) => emit('feedback', msg, r)"
          />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage } from '@/types/copilot'
import AnswerCard from './AnswerCard.vue'
import FeedbackBar from './FeedbackBar.vue'

defineProps<{ messages: ChatMessage[] }>()
const emit = defineEmits<{
  (e: 'feedback', msg: ChatMessage, rating: 'good' | 'bad'): void
}>()
</script>

<style scoped>
.message-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
}
.ml-empty {
  text-align: center;
  padding: 28px 12px;
  color: var(--ziwi-text-muted);
}
.ml-empty-emoji {
  font-size: 32px;
  margin-bottom: 8px;
}
.ml-empty-text {
  font-size: 14px;
  color: var(--ziwi-text-regular);
  margin-bottom: 4px;
}
.ml-empty-sub {
  font-size: 12px;
  line-height: 1.5;
}
.msg {
  display: flex;
}
.msg-user {
  justify-content: flex-end;
}
.msg-assistant {
  justify-content: flex-start;
}
.bubble {
  max-width: 88%;
  border-radius: var(--ziwi-radius-lg);
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.6;
}
.bubble-user {
  background: var(--ziwi-primary);
  color: #fff;
  border-top-right-radius: 2px;
}
.bubble-assistant {
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border);
  border-top-left-radius: 2px;
  width: 100%;
  max-width: 100%;
}
.loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ziwi-text-muted);
  font-size: 12px;
}
.notice {
  font-size: 13px;
  line-height: 1.6;
  padding: 6px 8px;
  border-radius: var(--ziwi-radius-sm);
}
.notice-reject {
  background: #fef2f2;
  color: var(--ziwi-danger);
}
.notice-clarify {
  background: #fffbeb;
  color: #b45309;
}
.notice-error {
  background: #fef2f2;
  color: var(--ziwi-danger);
}
</style>
