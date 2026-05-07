import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import { createAppI18n } from './i18n'
import { redirectInvalidBindHost } from './utils/canonicalHost'
import './styles/global.css'

if (!redirectInvalidBindHost()) {
  const app = createApp(App)
  const i18n = createAppI18n()

  app.use(createPinia())
  app.use(router)
  app.use(i18n)
  app.mount('#app')
}
