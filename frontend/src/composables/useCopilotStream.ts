/**
 * useCopilotStream —— SSE 消费 composable（组件内独立使用）。
 *
 * 与 store 共用同一底层 `askCopilotStream`；本 composable 适合在局部组件中
 * 维护独立的问答状态（不依赖 Pinia）。
 */
import { ref } from 'vue'
import { askCopilotStream } from '@/api/copilot'
import type { AnswerPayload, CopilotSseEvent } from '@/types/copilot'

export function useCopilotStream() {
  const answering = ref(false)
  const lastAnswer = ref<AnswerPayload | null>(null)
  const sessionId = ref<number | null>(null)
  const lastMessageId = ref<number | undefined>(undefined)
  const errorMessage = ref('')

  async function ask(
    question: string,
    onEvent?: (ev: CopilotSseEvent) => void,
  ): Promise<AnswerPayload | null> {
    answering.value = true
    errorMessage.value = ''
    let answer: AnswerPayload | null = null
    try {
      await askCopilotStream(question, sessionId.value, {
        onEvent: (ev) => {
          if (ev.type === 'session' && ev.session_id) sessionId.value = ev.session_id as number
          if (ev.type === 'answer') {
            answer = (ev.payload || null) as AnswerPayload | null
            lastAnswer.value = answer
            if (typeof ev.message_id === 'number') lastMessageId.value = ev.message_id as number
          }
          onEvent?.(ev)
        },
      })
    } catch (e: any) {
      errorMessage.value = e?.message || '请求失败'
    } finally {
      answering.value = false
    }
    return answer
  }

  function reset() {
    lastAnswer.value = null
    lastMessageId.value = undefined
    errorMessage.value = ''
  }

  return { answering, lastAnswer, sessionId, lastMessageId, errorMessage, ask, reset }
}
