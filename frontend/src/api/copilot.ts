/**
 * AI Copilot 接口封装（含 SSE 流式读取）。
 *
 * 说明：`/ask` 为 POST + SSE，浏览器 EventSource 仅支持 GET，
 * 故用 fetch + ReadableStream 手动解析 `data: {json}\n\n` 分帧。
 */
import { del, get, post } from '@/api/client'
import type { BriefingResult, CopilotSseEvent, SessionItem } from '@/types/copilot'

const BASE = '/api/v1/copilot'

export interface StreamHandlers {
  onEvent?: (ev: CopilotSseEvent) => void
  signal?: AbortSignal
}

/** 认证头（与 axios client 保持一致：Authorization + X-Tenant-Id）。 */
function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('access_token')
  const tenantId = localStorage.getItem('tenant_id')
  if (token) headers.Authorization = `Bearer ${token}`
  if (tenantId) headers['X-Tenant-Id'] = tenantId
  return headers
}

/**
 * 发起问数请求并消费 SSE 事件流。
 *
 * @param question   自然语言问句
 * @param sessionId  会话 ID（多轮上下文，可为 null）
 * @param handlers   事件回调与中断信号
 */
export async function askCopilotStream(
  question: string,
  sessionId: number | null,
  handlers: StreamHandlers = {},
): Promise<void> {
  const resp = await fetch(`${BASE}/ask`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ question, session_id: sessionId }),
    signal: handlers.signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`问数请求失败：HTTP ${resp.status}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const emitChunk = (chunk: string) => {
    for (const line of chunk.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data:')) continue
      const payload = trimmed.slice(5).trim()
      if (!payload) continue
      try {
        handlers.onEvent?.(JSON.parse(payload) as CopilotSseEvent)
      } catch {
        /* 忽略非法分帧 */
      }
    }
  }

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx = buffer.indexOf('\n\n')
    while (idx >= 0) {
      emitChunk(buffer.slice(0, idx))
      buffer = buffer.slice(idx + 2)
      idx = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) emitChunk(buffer)
}

/** 生成角色简报。 */
export async function getBriefing(role: string, date?: string): Promise<BriefingResult> {
  return post<BriefingResult>(`${BASE}/briefing`, { role, date })
}

/** 提交 👍/👎 反馈。 */
export async function sendFeedback(
  messageId: number,
  rating: 'good' | 'bad',
  reason?: string,
): Promise<{ id: number }> {
  return post<{ id: number }>(`${BASE}/feedback`, { message_id: messageId, rating, reason })
}

/** 会话列表。 */
export async function listSessions(): Promise<SessionItem[]> {
  return get<SessionItem[]>(`${BASE}/sessions`)
}

/** 删除会话。 */
export async function deleteSession(id: number): Promise<{ deleted: number }> {
  return del<{ deleted: number }>(`${BASE}/sessions/${id}`)
}
