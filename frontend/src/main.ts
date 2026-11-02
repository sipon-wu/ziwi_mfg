import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Vant from 'vant'
// ── 样式导入顺序（不可随意调换）──
// 1. 组件库基础样式
import 'vant/lib/index.css'
// 2. 变量 / 令牌层：品牌令牌 → 交互令牌 → 手套档覆盖 → 动效 → 工具集
//    ziwi-tokens.gloves.css 必须排在 ziwi-tokens.css 之后（同名变量按源序兜底）
import '@/styles/ziwi-variables.css'
import '@/styles/ziwi-tokens.css'
import '@/styles/ziwi-tokens.gloves.css'
import '@/styles/ziwi-motion.css'
import '@/styles/ziwi-utilities.css'
// 3. Vant 桥接必须最后：它读的是上面几层已声明的 --ziwi-* 变量
import '@/styles/vant-overrides.css'
import App from './App.vue'
import router from './router'
import SelectField from '@/components/SelectField.vue'
// ── T02 容器组件（架构 §5.2）──
// 全局注册的意义：`ziwi-*` 组件是"基础设施"，不是业务组件。86 个页面里凡是需要
// 浮层/选择器/状态视图的地方都应该能直接写标签，而不是每页 import 一遍；
// 更重要的是**不允许多份实现**（否则 R1–R4 就又散回页面了）。
import ZiwiFormSheet from '@/components/ziwi/ZiwiFormSheet.vue'
import ZiwiSelect from '@/components/ziwi/ZiwiSelect.vue'
import ZiwiSelectList from '@/components/ziwi/ZiwiSelectList.vue'
import ZiwiReceipt from '@/components/ziwi/ZiwiReceipt.vue'
import ZiwiStateView from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiConfirmSheet from '@/components/ziwi/ZiwiConfirmSheet.vue'
import ZiwiErrorSummary from '@/components/ziwi/ZiwiErrorSummary.vue'
import ZiwiFieldError from '@/components/ziwi/ZiwiFieldError.vue'
import ZiwiScanField from '@/components/ziwi/ZiwiScanField.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'
import ZiwiQtyField from '@/components/ziwi/ZiwiQtyField.vue'
import ZiwiActionBar from '@/components/ziwi/ZiwiActionBar.vue'
import perm from '@/directives/perm'
import { useAuthStore } from '@/stores/auth'
import { installFormFactor } from '@/composables/useFormFactor'
import { initGloveMode, syncGloveModeWithRole } from '@/composables/useGloveMode'

const app = createApp(App)
app.use(createPinia())

// 形态判定（W/T/H）：安装即下发 <html data-form-factor>，且响应式监听拖窗/旋屏。
// 必须在 mount 之前安装，保证首帧就带正确的形态属性（否则会闪一次错误布局）。
installFormFactor(app)

// 手套模式：先按设备记忆/角色默认给出初值，再下发 <html data-glove="on|off">
initGloveMode()

app.use(router)
app.use(Vant)
// 旧名薄壳（8 个 basics 页用全局名 `SelectField`，改动即白屏）
app.component('SelectField', SelectField)

// T02 容器组件全局注册：一份实现，全站复用（R1–R4 的唯一承载者）
const ziwiComponents = {
  ZiwiFormSheet,
  ZiwiSelect,
  ZiwiSelectList,
  ZiwiReceipt,
  ZiwiStateView,
  ZiwiConfirmSheet,
  ZiwiErrorSummary,
  ZiwiFieldError,
  ZiwiScanField,
  ZiwiCodeText,
  ZiwiQtyField,
  ZiwiActionBar,
} as const
for (const [name, component] of Object.entries(ziwiComponents)) {
  app.component(name, component)
}

// 按钮级权限门：v-perm="'M01:work_order:execute'" / v-perm:disable="[...]"
app.directive('perm', perm)

// 应用启动恢复会话：若本地有 token，重新拉取真实用户角色（修复硬刷新后菜单不全）
const auth = useAuthStore()
auth.init().finally(() => {
  // 角色已知后重新评估手套默认档（仅在用户从未显式设置过时才跟随角色）
  syncGloveModeWithRole()
  app.mount('#app')
})
