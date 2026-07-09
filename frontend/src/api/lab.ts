import { get, post, put, del } from './client'

export interface LabRequest {
  id: number
  tenant_id: string
  request_no: string
  title: string
  request_type: string
  source_type: string | null
  source_id: number | null
  priority: string
  sample_info: any
  description: string | null
  status: string
  assignee_id: number | null
  expected_date: string | null
  conclusion: string | null
  attachments: any
  created_by: number | null
  created_at: string
  updated_at: string
  test_results: LabTestResult[]
}

export interface LabTestResult {
  id: number
  request_id: number
  item_name: string
  spec_value: string | null
  actual_value: string | null
  unit: string | null
  lower_limit: number | null
  upper_limit: number | null
  is_pass: boolean | null
  remark: string | null
}

export interface TestStandard {
  id: number
  name: string
  category: string | null
  method: string | null
  default_lower_limit: number | null
  default_upper_limit: number | null
  unit: string | null
  description: string | null
  created_at: string
}

export interface LabCalibration {
  id: number
  equipment_name: string
  calibrate_type: string | null
  calibrate_date: string | null
  valid_until: string | null
  result: string | null
  certificate: string | null
  remark: string | null
}

export interface LabReport {
  id: number
  request_id: number
  report_no: string
  conclusion: string | null
  summary: string | null
  attachments: any
  published_by: number | null
  published_at: string | null
}

// 实验委托
export async function listRequests(params: {
  page?: number
  page_size?: number
  status?: string
  request_type?: string
  priority?: string
}): Promise<{ items: LabRequest[]; total: number; page: number; page_size: number }> {
  return get('/lab/requests', params)
}

export async function createRequest(data: any): Promise<LabRequest> {
  return post('/lab/requests', data)
}

export async function getRequest(id: number): Promise<LabRequest> {
  return get(`/lab/requests/${id}`)
}

export async function updateRequest(id: number, data: any): Promise<LabRequest> {
  return put(`/lab/requests/${id}`, data)
}

export async function receiveSample(id: number): Promise<LabRequest> {
  return post(`/lab/requests/${id}/receive`)
}

export async function assignTester(id: number, assignee_id: number): Promise<LabRequest> {
  return post(`/lab/requests/${id}/assign`, { assignee_id })
}

export async function startTesting(id: number): Promise<LabRequest> {
  return post(`/lab/requests/${id}/start`)
}

export async function submitResults(id: number, results: any[]): Promise<LabRequest> {
  return post(`/lab/requests/${id}/results`, { results })
}

export async function approveRequest(id: number): Promise<LabRequest> {
  return post(`/lab/requests/${id}/approve`)
}

export async function revertStatus(id: number): Promise<LabRequest> {
  return post(`/lab/requests/${id}/revert`)
}

export async function getReport(id: number): Promise<LabReport> {
  return get(`/lab/requests/${id}/report`)
}

export async function publishReport(id: number, conclusion: string, summary?: string, attachments?: string): Promise<LabReport> {
  return post(`/lab/requests/${id}/publish-report`, { conclusion, summary, attachments })
}

// 标准库
export async function listStandards(params: {
  page?: number
  page_size?: number
  category?: string
}): Promise<{ items: TestStandard[]; total: number; page: number; page_size: number }> {
  return get('/lab/standards', params)
}

export async function createStandard(data: any): Promise<TestStandard> {
  return post('/lab/standards', data)
}

export async function updateStandard(id: number, data: any): Promise<TestStandard> {
  return put(`/lab/standards/${id}`, data)
}

export async function deleteStandard(id: number): Promise<void> {
  return del(`/lab/standards/${id}`)
}

// 校准记录
export async function listCalibrations(params: {
  page?: number
  page_size?: number
}): Promise<{ items: LabCalibration[]; total: number; page: number; page_size: number }> {
  return get('/lab/calibrations', params)
}

export async function createCalibration(data: any): Promise<LabCalibration> {
  return post('/lab/calibrations', data)
}
