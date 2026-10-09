/* 全局状态：API Key / 演示模式 / 事件日志总线（模块级 reactive，无需 Pinia） */
import { reactive } from 'vue'

/* API Key 不随代码分发：首次使用请在页面「API 设置」中输入（保存于浏览器 localStorage） */
export const store = reactive({
  apiKey: localStorage.getItem('amphion_key') || '',
  demoMode: true,
  logs: []           // { time, msg, cls }
})

export function setApiKey(k) {
  store.apiKey = k.trim()
  localStorage.setItem('amphion_key', store.apiKey)
  log('API Key 已保存到 localStorage')
}

export function log(msg, cls) {
  const t = new Date().toTimeString().slice(0, 8)
  store.logs.push({ time: t, msg: String(msg), cls })
  if (store.logs.length > 500) store.logs.splice(0, store.logs.length - 500)
}

/* 调试日志：演示模式（默认开）下隐藏中间过程，只保留关键结果与错误 */
export function dlog(msg, cls) { if (!store.demoMode) log(msg, cls) }
