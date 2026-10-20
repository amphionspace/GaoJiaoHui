import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'
import { loadRuntimeConfig } from './core/api.js'

loadRuntimeConfig().then(() => createApp(App).mount('#app')).catch(() => {
  const root = document.querySelector('#app')
  root.textContent = '本地服务未连接或连接配置无效。请检查服务是否启动，刷新页面可重新连接。'
  root.setAttribute('role', 'alert')
})
