import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Vant from 'vant'
import 'vant/lib/index.css'
import '@/styles/vant-overrides.css'
import '@/styles/ziwi-variables.css'
import App from './App.vue'
import router from './router'
import SelectField from '@/components/SelectField.vue'
import perm from '@/directives/perm'
import { useAuthStore } from '@/stores/auth'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(Vant)
app.component('SelectField', SelectField)
// 按钮级权限门：v-perm="'M01:work_order:execute'" / v-perm:disable="[...]"
app.directive('perm', perm)

// 应用启动恢复会话：若本地有 token，重新拉取真实用户角色（修复硬刷新后菜单不全）
const auth = useAuthStore()
auth.init().finally(() => {
  app.mount('#app')
})
