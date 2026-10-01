/**
 * AI Copilot Pinia Store（会话 / 消息 / 上下文 / 反馈）。
 */
import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { askCopilotStream, getBriefing, sendFeedback } from '@/api/copilot'
import type { BriefingResult, ChatMessage, CopilotSseEvent } from '@/types/copilot'

let _seq = 0
function uid(prefix: string): string {
  _seq += 1
  return `${prefix}_${Date.now()}_${_seq}`
}

export const useCopilotStore = defineStore('copilot', () => {
  const drawerOpen = ref(false)
  const view = ref<'chat' | 'briefing'>('chat')
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<number | null>(null)
  const loading = ref(false)
  const briefing = ref<BriefingResult | null>(null)
  const briefingLoading = ref(false)

  function toggleDrawer(value?: boolean) {
    drawerOpen.value = value === undefined ? !drawerOpen.value : value
  }

  function setView(v: 'chat' | 'briefing') {
    view.value = v
  }

  /** 提问：追加用户与助手消息，消费 SSE 事件流并回填答案。 */
  async function ask(question: string) {
    const q = (question || '').trim()
    if (!q || loading.value) return

    messages.value.push({ id: uid('u'), role: 'user', question: q })
    // 关键：助手对象必须用 reactive 包装后再入队。
    // 否则 messages.value.push(rawObj) 存的是 raw 对象、模板读的是代理，直接改 raw
    // 对象的属性不触发 set trap → 助手气泡永久停在「正在分析…」（one-question lag）。
    const assistant = reactive<ChatMessage>({ id: uid('a'), role: 'assistant', loading: true })
    messages.value.push(assistant)
    loading.value = true

    const handle = (ev: CopilotSseEvent) => {
      switch (ev.type) {
        case 'session':
          if (ev.session_id) sessionId.value = ev.session_id as number
          break
        case 'intent':
          assistant.metricCode = ev.metric_code as string
          assistant.confidence = ev.confidence as number
          break
        case 'answer': {
          const payload = (ev.payload || {}) as ChatMessage['payload']
          assistant.payload = payload
          assistant.eventType = payload?.event === 'reject'
            ? 'reject'
            : payload?.event === 'clarify'
              ? 'clarify'
              : 'answer'
          assistant.message = payload?.narrative
          if (typeof ev.message_id === 'number') assistant.messageId = ev.message_id as number
          assistant.loading = false
          break
        }
        case 'reject':
        case 'clarify':
          assistant.eventType = ev.type as ChatMessage['eventType']
          assistant.message = ev.message as string
          break
        case 'error':
          assistant.eventType = 'error'
          assistant.message = (ev.message as string) || '处理异常'
          assistant.loading = false
          break
        default:
          break
      }
    }

    try {
      await askCopilotStream(q, sessionId.value, { onEvent: handle })
    } catch (e: any) {
      assistant.eventType = 'error'
      assistant.message = e?.message || '请求失败，请稍后重试'
    } finally {
      assistant.loading = false
      loading.value = false
    }
  }

  /** 加载角色简报。 */
  async function loadBriefing(role = '厂长') {
    briefingLoading.value = true
    try {
      briefing.value = await getBriefing(role)
    } finally {
      briefingLoading.value = false
    }
  }

  /** 提交反馈。 */
  async function feedback(messageId: number | undefined, rating: 'good' | 'bad', reason?: string) {
    if (!messageId) return
    try {
      await sendFeedback(messageId, rating, reason)
    } catch {
      /* 反馈失败静默处理，不打断体验 */
    }
  }

  /** 清空当前会话。 */
  function clear() {
    messages.value = []
    sessionId.value = null
  }

  return {
    drawerOpen,
    view,
    messages,
    sessionId,
    loading,
    briefing,
    briefingLoading,
    toggleDrawer,
    setView,
    ask,
    loadBriefing,
    feedback,
    clear,
  }
})
