import { onBeforeUnmount, onMounted, watch } from 'vue'

export const cancelled = () => new DOMException('会话已结束', 'AbortError')

export class Session {
  constructor() { this.controller = new AbortController(); this.controller.abort() }
  begin() { this.cancel(); this.controller = new AbortController(); return this.controller.signal }
  cancel() { this.controller.abort() }
  current(signal) { return signal === this.controller.signal && !signal.aborted }
}

export function useActivity(props, stop) {
  const hidden = () => { if (document.hidden) stop() }
  watch(() => props.active, active => { if (!active) stop() }, { flush: 'sync' })
  onMounted(() => {
    document.addEventListener('visibilitychange', hidden)
    window.addEventListener('pagehide', stop)
  })
  onBeforeUnmount(() => {
    stop()
    document.removeEventListener('visibilitychange', hidden)
    window.removeEventListener('pagehide', stop)
  })
}

export function openSocket(socket, signal, timeout = 12000) {
  return new Promise((resolve, reject) => {
    const finish = error => {
      clearTimeout(timer)
      socket.removeEventListener('open', opened)
      socket.removeEventListener('error', failed)
      socket.removeEventListener('close', failed)
      signal.removeEventListener('abort', aborted)
      if (error) { socket.close(); reject(error) } else resolve()
    }
    const opened = () => finish()
    const failed = () => finish(new Error('语音连接失败，请检查网络和密钥。'))
    const aborted = () => finish(cancelled())
    const timer = setTimeout(() => finish(new Error('语音连接超时，请重试。')), timeout)
    socket.addEventListener('open', opened)
    socket.addEventListener('error', failed)
    socket.addEventListener('close', failed)
    signal.addEventListener('abort', aborted, { once: true })
    if (signal.aborted) aborted()
  })
}

export function closeSocket(socket) {
  if (!socket) return
  socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null
  try { socket.close() } catch { /* Already closed. */ }
}

export function drainSocket(socket, timeout = 10000) {
  if (!socket || socket.readyState !== 1) { closeSocket(socket); return Promise.resolve(false) }
  return new Promise(resolve => {
    const finish = complete => {
      clearTimeout(timer)
      socket.removeEventListener('message', message)
      socket.removeEventListener('close', closed)
      closeSocket(socket); resolve(complete)
    }
    const message = event => {
      try { if (JSON.parse(event.data).type === 'session.done') finish(true) } catch { /* Binary data. */ }
    }
    const closed = () => finish(false)
    const timer = setTimeout(() => finish(false), timeout)
    socket.addEventListener('message', message)
    socket.addEventListener('close', closed)
    try { socket.send(JSON.stringify({ type: 'input_audio_buffer.commit' })) }
    catch { finish(false) }
  })
}
