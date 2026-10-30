/**
 * v-perm —— 按钮 / 操作级权限门。
 *
 * 为什么需要它
 * ------------
 * 路由守卫只能挡住"整页不可见"，挡不住"同一页里的某个动作不可用"。
 * 之前所有动作按钮都是一视同仁地渲染出来，能不能点全看后端：
 * 没有权限的用户点下去才收到 403 —— 用户看到的是"系统坏了"，
 * 而不是"这事不归我管"。
 *
 * 设计取舍
 * ----------
 * 1. **只控制显示，不做安全边界**。真正的拦截永远在后端
 *    `permission_guard`；前端这层是为了让界面说实话。
 * 2. **未声明权限码 = 不控制**（`v-perm` 传空值时不隐藏），
 *    这样存量页面可以逐个接入，不会一夜之间全空。
 * 3. 两种模式：
 *    - 默认：无权限直接隐藏（`display:none`，不占位）
 *    - `v-perm:disable`：无权限置灰禁用（按钮组布局需要保持占位时用）
 * 4. 权限在 `main.ts` 里 `auth.init()` 完成后才 mount，所以指令挂载时
 *    权限集合已经就绪；配合 `updated` 兜住运行期权限变化。
 */
import type { Directive, DirectiveBinding } from 'vue'
import { useAuthStore } from '@/stores/auth'

type PermValue = string | string[] | null | undefined

function granted(value: PermValue): boolean {
  const codes = (Array.isArray(value) ? value : [value]).filter(
    (c): c is string => typeof c === 'string' && c.length > 0,
  )
  if (!codes.length) return true // 未声明就不控制
  const auth = useAuthStore()
  return codes.some((code) => auth.hasPerm(code))
}

function apply(el: HTMLElement, binding: DirectiveBinding<PermValue>) {
  const ok = granted(binding.value)

  if (binding.arg === 'disable') {
    // 禁用模式：保持占位，让用户知道"有这个动作但我不能做"
    el.toggleAttribute('disabled', !ok)
    el.style.opacity = ok ? '' : '0.45'
    el.style.pointerEvents = ok ? '' : 'none'
    el.setAttribute('aria-disabled', ok ? 'false' : 'true')
    return
  }

  // 隐藏模式：记住原始 display，权限变化后能还原
  if (el.dataset.permDisplay === undefined) {
    el.dataset.permDisplay = el.style.display || ''
  }
  el.style.display = ok ? el.dataset.permDisplay : 'none'
  if (ok) el.removeAttribute('data-perm-hidden')
  else el.setAttribute('data-perm-hidden', '1')
}

const perm: Directive<HTMLElement, PermValue> = {
  mounted: apply,
  updated: apply,
}

export default perm
