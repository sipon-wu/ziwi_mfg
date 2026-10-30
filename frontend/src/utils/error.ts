/**
 * 统一提取后端错误里"给人看的那句话"。
 *
 * 后端约定：业务错误抛 `HTTPException(status_code, detail={"code","message"})`。
 * 所以人话在 `e.response.data.detail.message`，**不在** `e.message`
 * （那是 axios 的 "Request failed with status code 400"，对用户毫无信息量）。
 *
 * 三种形状都要兼容：
 *   - detail 是对象 `{code, message}`  → 取 message（绝大多数业务错误）
 *   - detail 是字符串                  → 直接用（FastAPI 默认校验错误）
 *   - detail 是数组                    → Pydantic 422 校验错误，取第一条的 msg
 */
export function errMessage(e: any, fallback = '操作失败，请重试'): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string' && d) return d
  if (Array.isArray(d) && d.length) {
    const first = d[0]
    if (typeof first === 'string') return first
    if (first && typeof first === 'object' && first.msg) return String(first.msg)
  }
  if (d && typeof d === 'object' && d.message) return String(d.message)
  const msg = e?.message
  // axios 自己的兜底文案（带 status code）不展示给用户
  if (typeof msg === 'string' && msg && !/^Request failed with status code/.test(msg)) return msg
  return fallback
}

/** 后端业务错误码（detail.code），用于分支处理，如 400-0003 = 零产出完工被拦 */
export function errCode(e: any): string | undefined {
  const d = e?.response?.data?.detail
  return d && typeof d === 'object' ? d.code : undefined
}
