/* 音频管线：采样转换 / WAV 编码 / 麦克风 / 文件解码 / 定速发送
   （自 demo.html 迁移，逻辑不变；纯函数 + 类，无 UI 依赖，可单测） */
export const SR = 16000
export const FRAME = 3200              // 16k s16le，100ms/帧(3200B)

export function floatTo16(f32) {       // Float32 -> Int16
  const out = new Int16Array(f32.length)
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]))
    out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
  }
  return out
}

export function resampleTo16k(f32, from) {  // 线性插值重采样
  if (from === SR) return f32
  const ratio = from / SR, n = Math.floor(f32.length / ratio)
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) { const p = i * ratio, j = Math.floor(p), f = p - j
    out[i] = f32[j] * (1 - f) + (f32[j + 1] || 0) * f }
  return out
}

export function wavEncode(pcmChunks) { // Int16Array[] -> WAV Blob (16k/16bit/mono)
  const total = pcmChunks.reduce((s, c) => s + c.length, 0)
  const buf = new ArrayBuffer(44 + total * 2), v = new DataView(buf)
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)) }
  ws(0, 'RIFF'); v.setUint32(4, 36 + total * 2, true); ws(8, 'WAVE')
  ws(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, SR, true); v.setUint32(28, SR * 2, true); v.setUint16(32, 2, true)
  v.setUint16(34, 16, true); ws(36, 'data'); v.setUint32(40, total * 2, true)
  let o = 44; for (const c of pcmChunks) { for (let i = 0; i < c.length; i++, o += 2) v.setInt16(o, c[i], true) }
  return new Blob([buf], {type: 'audio/wav'})
}

export function b64frame(f) {          // Int16Array 帧 -> base64
  const u8 = new Uint8Array(f.buffer, f.byteOffset, f.byteLength)
  let s = ''; for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i])
  return btoa(s)
}

/* getUserMedia 失败 -> 中文分类指引（Safari 的 "The object can not be found here." 等含糊文案在此归因） */
export function explainMicError(e) {
  const n = (e && e.name) || '', m = (e && e.message) || ''
  if (n === 'NotAllowedError' || /not allowed|denied|permission/i.test(m))
    return '麦克风权限被拒绝：请点地址栏左侧图标允许麦克风，并检查 系统设置→隐私与安全性→麦克风 已勾选当前浏览器'
  if (n === 'NotFoundError' || /can ?not be found|not found|no available/i.test(m))
    return '未找到可用麦克风（' + (m || n) + '）：请确认 ①系统设置→隐私与安全性→麦克风 已允许当前浏览器 ②麦克风已连接且未被其他应用独占；暂无设备时可改用「音频文件测试」'
  if (n === 'NotReadableError' || /could not start/i.test(m))
    return '麦克风被其他应用占用：请关闭正在使用麦克风的应用后重试'
  return '麦克风不可用：' + (m || n || '未知错误')
}

/* 麦克风：AudioContext(16k) + ScriptProcessor；onChunk(Int16Array)；collect 可选收集 */
export class Mic {
  constructor() { this.ctx = null; this.stream = null; this.proc = null }
  async start(onChunk, collect) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
      throw new Error('当前环境不支持麦克风采集（navigator.mediaDevices 不可用），请换 Chrome/Safari 标准窗口或用「音频文件测试」')
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false}})
    } catch (e) { throw new Error(explainMicError(e)) }
    try { this.ctx = new AudioContext({sampleRate: SR, latencyHint: 'interactive'}) }
    catch (e) { this.ctx = new AudioContext() }
    if (this.ctx.state === 'suspended') {   /* Safari/自动播放策略：非点击手势同步栈内创建的 ctx 为 suspended，不 resume 则 onaudioprocess 永不触发（零帧无转写） */
      try { await this.ctx.resume() } catch (e) { /* resume 失败由调用方的零帧提示兜底 */ }
    }
    const src = this.ctx.createMediaStreamSource(this.stream)
    this.proc = this.ctx.createScriptProcessor(2048, 1, 1)
    this.proc.onaudioprocess = ev => {
      const pcm = floatTo16(resampleTo16k(ev.inputBuffer.getChannelData(0), this.ctx.sampleRate))
      if (collect) collect.push(pcm)
      onChunk(pcm)
    }
    src.connect(this.proc); this.proc.connect(this.ctx.destination)
  }
  stop() {
    try { this.proc && this.proc.disconnect(); } catch (e) {}
    try { this.stream && this.stream.getTracks().forEach(t => t.stop()); } catch (e) {}
    try { this.ctx && this.ctx.close(); } catch (e) {}
    this.proc = this.stream = this.ctx = null
  }
}

/* 文件 -> 16k Int16 PCM（decodeAudioData 任意格式） */
export async function fileToPCM(file) {
  const ab = await file.arrayBuffer()
  const ctx = new (window.AudioContext || window.webkitAudioContext)()
  const buf = await ctx.decodeAudioData(ab); ctx.close()
  return floatTo16(resampleTo16k(buf.getChannelData(0), buf.sampleRate))
}

/* 按 1× 实时速率发送 PCM：onFrame 每 100ms 一帧 */
export async function streamPCM(pcm, onFrame, stopFlag) {
  for (let i = 0; i < pcm.length; i += FRAME) {
    if (stopFlag && stopFlag()) return
    onFrame(pcm.subarray(i, i + FRAME))
    await new Promise(r => setTimeout(r, 100))
  }
}
