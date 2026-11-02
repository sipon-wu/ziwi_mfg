/**
 * 打印留痕接口。
 *
 * ## 为什么不是 `window.print()`
 *
 * 纸质单据在制造业是审核证据。浏览器直接打印有三件事无法保证：打印时间与
 * 打印人能被改、打完改单就说不清"当时纸上写的什么"、同一单打十次分不清原件。
 * 所以 PDF 由服务端生成：留痕码、副本号、版本号、打印时间、打印人都写死在
 * PDF 字节里，前端拿不到也改不了。
 *
 * ## 三个接口的语义差别（最容易混淆的地方）
 *
 * | 接口 | 语义 | 什么时候用 |
 * |---|---|---|
 * | `renderPrint` | **重打**：用**当前**数据出一份新纸，副本号 +1 | 详情页点「打印」 |
 * | `fetchArtifactPdf` | **补打**：取**当时那张纸的字节**，不重新生成 | 审核补材料、回看历史纸 |
 * | `verifyArtifact` | 扫码回查：这张纸真不真、还有效吗 | 二维码扫出来 |
 *
 * 审核补材料**必须**用补打。用重打补出来的纸内容与当初交出去的不一致，
 * 等于伪造。
 */
import client from './client'

/** 一次打印产生的留痕信息（服务端写在响应头 `X-Print-*` 上）。 */
export interface PrintArtifactMeta {
  artifactId: number
  docNo: string
  verifyCode: string
  revision: number
  copyNo: number
  pageCount: number
  template: string
  printedAt: string
}

export interface RenderedPrint {
  /** PDF 字节 */
  blob: Blob
  /** `URL.createObjectURL(blob)`，**调用方负责 revoke**（不 revoke 会一直占内存） */
  url: string
  meta: PrintArtifactMeta
}

export interface PrintArtifactRow {
  id: number
  doc_type: string
  doc_id: string
  doc_no: string | null
  doc_revision: number
  copy_no: number
  doc_status: string | null
  template_code: string
  template_version: string
  content_hash: string
  printed_by_name: string | null
  print_source: string | null
  status: 'valid' | 'superseded' | 'voided'
  superseded_by: number | null
  verify_code: string
  page_count: number
  file_size: number
  created_at: string
}

export interface PrintVerifyResult {
  found: boolean
  verify_code: string
  doc_type?: string
  doc_no?: string
  title?: string
  doc_status?: string | null
  doc_revision?: number
  copy_no?: number
  template?: string
  content_hash?: string
  printed_by_name?: string | null
  printed_at?: string | null
  page_count?: number
  valid?: boolean
  status?: string
  superseded_by?: number | null
}

/**
 * 把二进制端点上的错误响应解析成可读文案。
 *
 * `responseType: 'blob'` 时后端返回的 JSON 也被包成 Blob，axios 的
 * `error.response.data.detail` 取不到 —— 不处理的话打印失败只会显示
 * 「操作失败」，车间无法判断是权限、单据不存在还是字体缺失。
 */
async function blobErrorText(error: any, fallback: string): Promise<string> {
  const data = error?.response?.data
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text())
      const detail = parsed?.detail
      if (typeof detail === 'string' && detail) return detail
      if (typeof detail?.message === 'string' && detail.message) return detail.message
      if (typeof parsed?.message === 'string' && parsed.message) return parsed.message
    } catch {
      /* 不是 JSON → 用兜底文案 */
    }
  }
  return fallback
}

/** 重打：用当前数据出一份新纸（会落一条新留痕，副本号 +1）。 */
export async function renderPrint(
  docType: string,
  docId: string | number,
): Promise<RenderedPrint> {
  let res
  try {
    res = await client.post(`/print/${docType}/${docId}`, null, { responseType: 'blob' })
  } catch (e: any) {
    // 抛出的错误对象里挂上可读文案，调用方直接取 `.readable`
    const err: any = new Error(await blobErrorText(e, '打印失败'))
    err.readable = err.message
    throw err
  }
  const blob: Blob = res.data
  const h = res.headers || {}
  return {
    blob,
    url: URL.createObjectURL(blob),
    meta: {
      artifactId: Number(h['x-print-artifact-id'] || 0),
      docNo: String(h['x-print-doc-no'] || ''),
      verifyCode: String(h['x-print-verify-code'] || ''),
      revision: Number(h['x-print-revision'] || 1),
      copyNo: Number(h['x-print-copy-no'] || 1),
      pageCount: Number(h['x-print-page-count'] || 1),
      template: String(h['x-print-template'] || ''),
      printedAt: String(h['x-print-at'] || ''),
    },
  }
}

/** 补打：取历史那份 PDF 的原始字节（不重新生成内容）。 */
export async function fetchArtifactPdf(artifactId: number): Promise<Blob> {
  const res = await client.get(`/print/artifacts/${artifactId}/pdf`, { responseType: 'blob' })
  return res.data
}

/** 留痕列表（不含 PDF 字节）。 */
export async function listArtifacts(params: {
  doc_type?: string
  doc_id?: string | number
  status?: string
  page?: number
  page_size?: number
}): Promise<{ items: PrintArtifactRow[]; total: number; page: number; page_size: number }> {
  const { data } = await client.get('/print/artifacts', { params })
  return data.data ?? data
}

/** 扫码回查。 */
export async function verifyArtifact(code: string): Promise<PrintVerifyResult> {
  const { data } = await client.get(`/print/verify/${encodeURIComponent(code)}`)
  return data.data ?? data
}

/** 触发浏览器打印。
 *
 * 分两步是因为 Chrome 的 PDF 插件不接受父窗口的 `print()`（会静默无事发生），
 * 而 Firefox / 部分国产壳子可以。所以先试 iframe，失败则让用户用预览器自带的
 * 打印按钮 —— 比起"点了没反应"，明确告知下一步更有用。
 *
 * @returns true 表示已经通过父窗口发起打印
 */
export function triggerPrint(frame: HTMLIFrameElement | null): boolean {
  try {
    frame?.contentWindow?.focus()
    frame?.contentWindow?.print()
    return true
  } catch {
    return false
  }
}
