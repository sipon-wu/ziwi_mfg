/**
 * 知微 ziwi · 前端枚举单一真源
 *
 * 为什么要有这个文件：`OP_TYPE` 原本在 `OperationList.vue` 和 `searchFields.ts`
 * 各存了一份一模一样的 11 项常量，两处都漏了 `incoming_qc / process_qc /
 * final_qc` —— 而这三个值库里真有（艾华推进器场景的「定子电检（第一次）」
 * 就是 `process_qc`）。于是列表「工序类型」列直接印英文原文。
 *
 * 约定：前端所有枚举只准从这里取；后端真源是 `backend/app/core/enums.py`，
 * 两侧一致性由 `backend/app/tests/test_op_type_domain.py` 断言。
 */

export interface EnumOption {
  value: string
  label: string
}

/**
 * 工序类型。顺序与后端 `OP_TYPE_LABELS` 一致（dict 保持插入序）：
 * 先加工/装配类主类型，再把三种检验（来料/过程/终检）排在一起。
 */
export const OP_TYPE_OPTIONS: EnumOption[] = [
  { value: 'machining', label: '机加工' },
  { value: 'assembly', label: '装配' },
  { value: 'heat_treat', label: '热处理' },
  { value: 'surface_treat', label: '表面处理' },
  { value: 'inspect', label: '检验' },
  { value: 'incoming_qc', label: '来料检' },
  { value: 'process_qc', label: '过程检' },
  { value: 'final_qc', label: '终检' },
  { value: 'pack', label: '包装' },
  { value: 'reaction', label: '反应' },
  { value: 'blend', label: '混合' },
  { value: 'separation', label: '分离' },
  { value: 'filling', label: '灌装' },
  { value: 'transport', label: '转运' },
]

/**
 * 代码 → 中文标签。未知值给「未知（原文）」而不是回显原文。
 *
 * ⚠️ 兜底回显原文会让**脏数据看起来像正常值**：用户看到 `production`
 * 只会以为"这个系统就是显示英文的"，而不会想到库里存了个非法值。
 * `mfg_demo` 的 65 条探针工序正是这么藏了三轮没被发现。
 */
export function opTypeLabel(code: string | null | undefined): string {
  if (!code) return ''
  const hit = OP_TYPE_OPTIONS.find((o) => o.value === code)
  return hit ? hit.label : `未知（${code}）`
}
