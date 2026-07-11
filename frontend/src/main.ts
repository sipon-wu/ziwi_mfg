import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Vant from 'vant'
import 'vant/lib/index.css'
import '@/styles/vant-overrides.css'
import '@/styles/ziwi-variables.css'
import App from './App.vue'
import router from './router'
import SelectField from '@/components/SelectField.vue'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(Vant)
app.component('SelectField', SelectField)
app.mount('#app')
