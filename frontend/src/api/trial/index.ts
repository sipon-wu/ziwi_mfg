import { get, post, put } from '@/api/client'
import type { ApiResponse } from '@/types/api'

export interface TrialOrder {
  id: number
  order_no: string
  trial_type: string
  status: string
  product_id: number | null
  product_name: string
  product_spec: string | null
  planned_qty: number | null
  completed_qty: number
  priority: number
  lab_required: boolean
  scheme_json: any
  target_json: any
  key_params: any
  inspection_plan: any
  started_at: string | null
  completed_at: string | null
  terminated_reason: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface TrialRoute {
  id: number
  trial_order_id: number
  route_json: any
  source_type: string
  source_route_id: number | null
  name: string | null
  description: string | null
  change_notes: string | null
  is_active: boolean
}

export interface TrialBom {
  id: number
  trial_order_id: number
  bom_json: any
  source_type: string
  source_bom_id: number | null
}

export interface TrialReview {
  id: number
  trial_order_id: number
  review_stage: string | null
  conclusion: string
  review_items: any
  summary_data: any
  summary_attachments: any
  reviewer: number | null
  reviewed_at: string | null
  created_at: string
}

export interface PaginatedData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// 试产工单
export function listTrials(params?: { page?: number; page_size?: number; trial_type?: string; status?: string }) {
  return get<PaginatedData<TrialOrder>>('/trials', params)
}

export function createTrial(data: any) {
  return post<TrialOrder>('/trials', data)
}

export function getTrial(id: number) {
  return get<TrialOrder>(`/trials/${id}`)
}

export function updateTrial(id: number, data: any) {
  return put<any>(`/trials/${id}`, data)
}

export function advanceStage(id: number, target_stage?: string) {
  return post<any>(`/trials/${id}/advance`, { target_stage })
}

// 试产路线
export function getTrialRoute(orderId: number) {
  return get<TrialRoute>(`/trials/${orderId}/routes`)
}

export function saveTrialRoute(orderId: number, data: any) {
  return put<any>(`/trials/${orderId}/routes`, data)
}

// 试产BOM
export function getTrialBom(orderId: number) {
  return get<TrialBom>(`/trials/${orderId}/bom`)
}

export function saveTrialBom(orderId: number, data: any) {
  return put<any>(`/trials/${orderId}/bom`, data)
}

// 评审
export function submitReview(orderId: number, data: any) {
  return post<any>(`/trials/${orderId}/review`, data)
}

export function listReviews(orderId: number) {
  return get<TrialReview[]>(`/trials/${orderId}/reviews`)
}

export function makeReviewDecision(orderId: number, reviewId: number, data: any) {
  return post<any>(`/trials/${orderId}/reviews/${reviewId}/decide`, data)
}

// 操作
export function convertToProduction(orderId: number) {
  return post<any>(`/trials/${orderId}/convert`)
}

export function terminateTrial(orderId: number, terminated_reason?: string) {
  return post<any>(`/trials/${orderId}/terminate`, { terminated_reason })
}

export function importBom(orderId: number, source_id: number) {
  return post<any>(`/trials/${orderId}/import-bom`, { source_id })
}

export function importRoute(orderId: number, source_id: number) {
  return post<any>(`/trials/${orderId}/import-route`, { source_id })
}
