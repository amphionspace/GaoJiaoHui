/* Amphion 网关 HTTP 客户端：经本地 FastAPI /proxy 同源转发（网关未开 CORS）
   WS 仍由浏览器直连 wss://amphion.top（不受 CORS 限制） */
import { store } from './store.js'

export const WS_HOST = 'wss://amphion.top'
// cn-test 迁移期（2026-10）：/asr/v1/realtime 仅存在于 legacy 网关（106.52.52.196，新集群 404）。
// 浏览器 WS 直连域名会落到新集群，故经 bms910 Caddy 的 /ws-legacy 反代到 legacy（Host/SNI 仍 amphion.top）。
// WS 不受 CORS 限制，本地开发也可直连该地址。target-dialogue 仍走 WS_HOST（新集群已迁移，101 正常）。
export const WS_HOST_LEGACY = 'wss://amphion-gjh.amphiondev.com/ws-legacy'

export async function api(path, opts = {}) {
  opts.headers = Object.assign({ 'X-API-Key': store.apiKey }, opts.headers || {})
  const r = await fetch('/proxy' + path, opts)
  const ct = r.headers.get('content-type') || ''
  const body = ct.includes('json') ? await r.json() : await r.blob()
  if (!r.ok) throw Object.assign(new Error(typeof body === 'object' && body.detail
    ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)) : 'HTTP ' + r.status),
    { status: r.status, body })
  return body
}

/* ephemeral token（一次性 JWT，接口二优先使用，失败退回 ?api_key= 直连） */
export async function getEphemeralToken() {
  const r = await api('/auth/v1/ephemeral-tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resource: 'asr.target_dialogue', expires_in_seconds: 180, max_session_seconds: 180 })
  })
  const tok = r.access_token || r.token || (typeof r === 'string' ? r : null)
  if (!tok) throw new Error('响应无 access_token 字段: ' + JSON.stringify(r).slice(0, 120))
  return tok
}
