/**
 * AI Copilot 前端类型定义（对齐后端 Pydantic 契约）。
 */

export interface SourceFootnote {
  modules: string
  table_or_caliber: string
  caliber: string
  time_range: string
  record_count: number
  note?: string | null
}

export interface AnswerCardItem {
  metric_code: string
  name?: string
  unit?: string
  value?: number | null
  formatted?: string
  available: boolean
  note?: string | null
}

export interface AnswerColumn {
  key: string
  label: string
}

export interface AnswerData {
  metric_code?: string
  name?: string
  unit?: string
  value?: number | null
  formatted?: string
  available?: boolean
  answered?: boolean
  note?: string | null
  record_count?: number
  labels?: (string | null)[]
  rows?: Record<string, any>[]
  columns?: AnswerColumn[]
  series?: { name: any; value: any }[]
  cards?: AnswerCardItem[]
}

export interface AnswerPayload {
  narrative: string
  /** metric | table | line | bar | metric+line */
  viz_hint: string
  data: AnswerData
  source: SourceFootnote | null
  metric_code: string
  answered: boolean
  /** answer | reject | clarify | error */
  event: string
}

export interface CopilotSseEvent {
  type: string
  [key: string]: any
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  question?: string
  payload?: AnswerPayload
  eventType?: 'answer' | 'reject' | 'clarify' | 'error'
  message?: string
  messageId?: number
  metricCode?: string
  confidence?: number
  loading?: boolean
}

export interface BriefingCard {
  label: string
  metric_code: string
  unit?: string
  viz_hint?: string
  value?: number | null
  formatted?: string
  available: boolean
  note?: string | null
}

export interface BriefingResult {
  role: string
  title: string
  date?: string | null
  cards: BriefingCard[]
  note?: string
}

export interface FeedbackRequest {
  message_id: number
  rating: 'good' | 'bad'
  reason?: string
}

export interface SessionItem {
  id: number
  title?: string
  created_at?: string
  last_active_at?: string
}
