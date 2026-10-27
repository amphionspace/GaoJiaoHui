<script setup>
/* Reference registration and ordered playback use the configured gateway. */
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { WS_HOST, boundedFetch } from '../core/api.js'
import { store, setApiKey, log, dlog } from '../core/store.js'
import { SR, Mic, wavEncode, fileToPCM } from '../core/audio.js'
import { Session, useActivity, openSocket, closeSocket, drainSocket, cancelled } from '../core/session.js'
import { JourneySound } from '../core/journeyAudio.js'
import { SpeechQueue, speechChunks } from '../core/speechQueue.js'

const props = defineProps({ active: { type: Boolean, default: true } })
const session = new Session(), reference = new Session(), requests = new Session()
const connecting = ref(false)
let sound = null
const speech = new SpeechQueue(() => sound?.stop())
useActivity(props, suspend)
watch(() => store.apiKey, suspend)
function output() { sound ||= new JourneySound(); sound.unlock(); return sound }

const SESSION_MAX = 1800                 // 会话时长上限（秒，同工作台）
const TTS_MAX_CHARS = 120                // 单次合成文本上限（防超长 TTS）
const DEFAULT_VOICE = 'gjh_speaker1'

/* ---------- 顶栏 Key 同步 ---------- */
const keyInput = ref(store.apiKey)
watch(() => store.apiKey, k => { keyInput.value = k })

/* ---------- 左卡：克隆注册 ---------- */
const voiceName = ref(DEFAULT_VOICE)
const recBtnTxt = ref('录制参考音频')
const recTimerTxt = ref('')
const recInfo = ref('未录制')
const cloneResult = ref('')
const cloneBusy = ref(false)
const chunks = ref([])
const refFileInput = ref(null)
const voices = ref([])
const voiceSel = ref('')
const voicesNote = ref('')
const ttsModel = ref('')                   // ''=省略 model → 网关默认后端（cn-test 迁移期短名均 404）
const probeText = ref(store.locale === 'en' ? 'Leave a line for yourself today. Take your time, and keep moving forward.' : '给今天的自己留一句话，慢慢来，也可以继续向前。')
const probeSt = ref('')

let recMic = null, recTimer = null, recStart = 0, refBlob = null

async function jfetch(path, opts = {}) {
  let r
  try {
    r = await boundedFetch('/proxy' + path, { ...opts, headers: { 'X-API-Key': keyInput.value.trim(), ...(opts.headers || {}) } }, 120000)
  } catch (e) { throw Object.assign(new Error('无法连接网关：' + e.message), { status: 0 }) }
  if (!r.ok) {
    let detail = 'HTTP ' + r.status
    try { const b = await r.json(); detail = b.detail || b.message || detail } catch (e) { /* 非 JSON */ }
    throw Object.assign(new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)), { status: r.status })
  }
  return r.status === 204 ? null : r.json()
}

/* blob 版（/tts/v1/audio/speech 返回整段 WAV，非 JSON） */
async function jfetchBlob(path, opts = {}) {
  const r = await boundedFetch('/proxy' + path, { ...opts, headers: { 'X-API-Key': keyInput.value.trim(), ...(opts.headers || {}) } }, 240000)
  if (!r.ok) {
    let detail = 'HTTP ' + r.status
    try { const b = await r.json(); detail = b.detail || b.message || detail } catch (e) { /* 非 JSON */ }
    throw Object.assign(new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)), { status: r.status })
  }
  return r.blob()
}

async function toggleRec() {
  if (recMic) {                                       // 停止录制
    clearInterval(recTimer); recMic.stop(); recMic = null
    const dur = chunks.value.reduce((s, c) => s + c.length, 0) / SR
    recBtnTxt.value = '录制参考音频'; recTimerTxt.value = ''
    reference.cancel()
    if (dur < 5 || dur > 16) { recInfo.value = '请录制 5–15 秒清晰的单人讲话'; refBlob = null; return }
    let remaining = SR * 15
    const sample = []
    for (const chunk of chunks.value) {
      if (remaining <= 0) break
      sample.push(chunk.subarray(0, remaining)); remaining -= chunk.length
    }
    refBlob = wavEncode(sample)
    recInfo.value = `已录 ${dur.toFixed(1)}s · ${(refBlob.size / 1024).toFixed(0)}KB WAV · 可注册`
    log(`克隆：参考音频就绪（${dur.toFixed(1)}s）`, 'ok')
    return
  }
  if (!props.active) return
  const signal = reference.begin()
  chunks.value = []; refBlob = null
  const capture = recMic = new Mic()
  try { await capture.start(() => {}, chunks.value) }
  catch (e) { if (reference.current(signal)) { recMic = null; recInfo.value = '麦克风失败：' + e.message } return }
  if (!reference.current(signal)) { capture.stop(); return }
  recBtnTxt.value = '停止录制'; recStart = Date.now()
  recTimer = setInterval(() => {
    const s = (Date.now() - recStart) / 1000
    recTimerTxt.value = s.toFixed(1) + 's'
    if (s >= 15) toggleRec()
  }, 100)
}

async function onRefFile(f) {
  if (!props.active || recMic) return
  const signal = reference.begin()
  try {
    if (f.size > 10 * 1024 * 1024) throw new Error('文件需小于 10 MB')
    const pcm = await fileToPCM(f)
    if (!reference.current(signal)) return
    if (pcm.length / SR < 5 || pcm.length / SR > 15) throw new Error('参考音频需为 5–15 秒')
    refBlob = wavEncode([pcm]); chunks.value = [pcm]
    recInfo.value = `文件 ${f.name} · ${(pcm.length / SR).toFixed(1)}s · ${(refBlob.size / 1024).toFixed(0)}KB`
    log(`克隆：参考文件已解码（${(pcm.length / SR).toFixed(1)}s）`, 'ok')
  } catch (e) { recInfo.value = '解码失败：' + e.message }
}
function pickRefFile() { refFileInput.value && refFileInput.value.click() }
function onRefFileInput(e) { const f = e.target.files[0]; if (f) onRefFile(f); e.target.value = '' }

async function cloneVoice() {
  if (!props.active || cloneBusy.value) return
  const signal = requests.begin()
  const name = voiceName.value.trim()
  if (!refBlob) return log('克隆：请先录制或选择参考音频', 'err')
  if (!/^[A-Za-z0-9_\-]{1,64}$/.test(name)) return log('克隆：音色名需为英文/数字/下划线', 'err')
  cloneBusy.value = true; cloneResult.value = '上传复刻中…'
  const t0 = performance.now()
  try {
    const fd = new FormData()
    fd.append('voice_name', name)
    fd.append('audio_file', refBlob, name + '.wav')
    await jfetch('/tts/v1/audio/voices', { method: 'POST', body: fd, signal })
    if (!requests.current(signal)) return
    const dt = ((performance.now() - t0) / 1000).toFixed(1)
    cloneResult.value = `音色注册成功（${dt}s）`
    log(`克隆：音色「${name}」注册成功（${dt}s）`, 'ok')
    await listVoices(name)
  } catch (e) {
    if (!requests.current(signal)) return
    cloneResult.value = '失败：' + e.message + (e.status === 409 ? '（同名已存在或配额满，可先删除）' : '')
    log('克隆：注册失败 ' + e.message, 'err')
  } finally { if (requests.current(signal)) cloneBusy.value = false }
}

async function listVoices(prefer) {
  try {
    const r = await jfetch('/tts/v1/audio/voices')
    const list = (r.voices || r.uploaded_voices || r.items || (Array.isArray(r) ? r : []))
      .map(v => typeof v === 'string' ? v : v.voice_name || v.name || v.id).filter(Boolean)
    voices.value = list
    voicesNote.value = `共 ${list.length} 个音色`
    if (prefer && list.includes(prefer)) voiceSel.value = prefer
    else if (!voiceSel.value || !list.includes(voiceSel.value)) voiceSel.value = list[0] || ''
  } catch (e) {
    voicesNote.value = '音色列表读取失败：' + e.message
  }
}

async function delVoice() {
  const voice = voiceSel.value
  if (!voice) return
  if (!confirm(`删除音色 ${voice}？`)) return
  try {
    await jfetch('/tts/v1/audio/voices/' + encodeURIComponent(voice), { method: 'DELETE' })
    log('克隆：已删除 ' + voice, 'ok'); await listVoices()
  } catch (e) { log('克隆：删除失败 ' + e.message, 'err') }
}

/* 试听：验证克隆音色可用（不进队列，直接播） */
async function probeSpeak() {
  if (!props.active || running.value || connecting.value) return
  if (!voiceSel.value) return log('克隆：请先选择音色', 'err')
  output(); speech.reset()
  const text = probeText.value.trim() || '测试'
  probeSt.value = '合成中…'
  const t0 = performance.now()
  try {
    await speech.add(async signal => {
      for (const part of speechChunks(text)) {
        const blob = await synthesize(voiceSel.value, part, signal)
        if (signal.aborted) return
        if (!await playBlob(blob)) return
      }
      if (!signal.aborted) probeSt.value = `试听完成 · ${((performance.now() - t0) / 1000).toFixed(1)}s`
    })
  } catch (e) { probeSt.value = '失败：' + e.message; log('克隆：试听失败 ' + e.message, 'err') }
}

function synthesize(voice, text, signal) {
  const payload = { voice, input: text,
    response_format: 'wav', sample_rate: 24000 }
  if (ttsModel.value) payload.model = ttsModel.value
  return jfetchBlob('/tts/v1/audio/speech', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload), signal,
  })
}
async function playBlob(blob) {
  const url = URL.createObjectURL(blob)
  try { return await output().play(url) }
  finally { URL.revokeObjectURL(url) }
}

/* ---------- 右卡：实时变声会话 ---------- */
const running = ref(false)
const connText = ref('未开始')
const connKind = ref('idle')               // idle | connecting | ready
const clock = ref('00:00')
const hint = ref('克隆音色就绪后，点击麦克风开始——说出的话将以该音色实时复述')
const doneInfo = ref('')
const meterW = ref(0)
const turns = ref([])
const listEl = ref(null)

let ws = null, mic = null, startedAt = 0, clockTimer = null, micWatchTimer = null
let sentFrames = 0, micWarned = false, sessionReadyResolve = null, sessionReadyReject = null
let stopping = false
const finalSegments = new Set()

function nowStr() { const d = new Date(); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}` }

async function startSession() {
  if (!props.active || connecting.value || running.value) return
  teardown(false)
  const signal = session.begin()
  connecting.value = true
  output(); speech.reset()
  try {
    if (!keyInput.value.trim()) throw new Error('请先在顶栏填写 API Key')
    if (!voiceSel.value) throw new Error('请先在左卡注册/选择克隆音色')
    clearTurns(); finalSegments.clear(); doneInfo.value = ''; meterW.value = 0
    sentFrames = 0; micWarned = false; stopping = false
    connText.value = '正在建立识别链路…'; connKind.value = 'connecting'

    /* 一次性 JWT（免长期 Key 走 WS），失败退回 ?api_key= 直连 */
    let token = null
    try {
      token = await jfetch('/auth/v1/ephemeral-tokens', {
        signal,
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resource: 'asr.target_dialogue', expires_in_seconds: 60, max_session_seconds: SESSION_MAX }),
      })
    } catch (e) { dlog('克隆会话：token 签发失败（' + e.message + '），退回 ?api_key=', 'evt') }
    if (!session.current(signal)) return

    const sock = new WebSocket(`${WS_HOST}/asr/v1/target-dialogue${token ? '' : '?api_key=' + encodeURIComponent(keyInput.value.trim())}`)
    sock.binaryType = 'arraybuffer'
    ws = sock
    await openSocket(sock, signal)
    if (!session.current(signal)) return
    sock.onmessage = ev => { if (!session.current(signal)) return; try { handleEvent(ev) } catch (e) { hint.value = '事件处理异常：' + e.message } }
    const sessionReady = new Promise((resolve, reject) => {
      const to = setTimeout(() => reject(new Error('识别链路准备超时')), 30000)
      const abort = () => { clearTimeout(to); reject(cancelled()) }
      signal.addEventListener('abort', abort, { once: true })
      sessionReadyResolve = () => { clearTimeout(to); signal.removeEventListener('abort', abort); resolve() }
      sessionReadyReject = err => { clearTimeout(to); signal.removeEventListener('abort', abort); reject(err) }
    })
    sock.onclose = ev => {
      if (!session.current(signal)) return
      sessionReadyReject && sessionReadyReject(new Error('WebSocket 在链路就绪前关闭'))
      if (running.value) {
        hint.value = ev.code === 4002 ? '余额不足（4002），连接被关闭' : `连接关闭（code ${ev.code}）`
        teardown(false)
      }
    }
    if (token) sock.send(JSON.stringify({ type: 'session.authenticate', access_token: token.access_token }))
    sock.send(JSON.stringify({
      type: 'session.update',
      session: {
        participants: [],                            // open 匿名分离：说话人2 无需注册声纹
        filter: { mode: 'open' },
        audio: { format: 'pcm_s16le', sample_rate_hz: SR, channels: 1 },
        recognition: { mode: 'role_separation', response_speed: 'balanced' },
      },
    }))
    try { await sessionReady } catch (e) { try { sock.close() } catch (err) { /* 忽略 */ } throw e }
    if (!session.current(signal)) return

    running.value = true; startedAt = Date.now()
    const capture = mic = new Mic()
    await capture.start(frame => {
      if (!session.current(signal) || !running.value || sock.readyState !== 1) return
      sentFrames++
      let sum = 0
      for (let i = 0; i < frame.length; i += 16) sum += frame[i] * frame[i]
      meterW.value = Math.min(100, Math.sqrt(sum / Math.ceil(frame.length / 16)) / 32768 * 260)
      sock.send(new Uint8Array(frame.buffer, frame.byteOffset, frame.byteLength))
    })
    if (!session.current(signal)) { capture.stop(); return }
    micWatchTimer = setTimeout(() => {
      if (running.value && sentFrames === 0 && !micWarned) {
        micWarned = true
        hint.value = '麦克风 3 秒内未采集到音频——请检查系统输入设备与浏览器权限'
      }
    }, 3000)
    clockTimer = setInterval(() => {
      const s = Math.floor((Date.now() - startedAt) / 1000)
      if (s >= SESSION_MAX) { stopSession(); return }
      clock.value = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
    }, 250)
    hint.value = `聆听中 · 说出的每句话将以「${voiceSel.value}」的音色复述`
    connText.value = '会话进行中'; connKind.value = 'ready'
    log(`克隆会话：开始（音色 ${voiceSel.value}）`, 'ok')
  } catch (e) {
    if (!session.current(signal)) return
    hint.value = '启动失败：' + e.message
    connText.value = '启动失败'; connKind.value = 'idle'
    if (mic) { mic.stop(); mic = null }
    if (ws) { try { ws.close() } catch (err) { /* 忽略 */ }; ws = null }
    running.value = false
  } finally { if (session.current(signal)) connecting.value = false }
}

/* ---------- WS 事件 ---------- */
function handleEvent(ev) {
  if (typeof ev.data !== 'string') return
  const d = JSON.parse(ev.data)
  const t = d.type || ''
  if (t === 'session.created') {
    sessionReadyResolve && sessionReadyResolve()
    sessionReadyResolve = sessionReadyReject = null
  } else if (t === 'transcription.partial' || t === 'transcription.final') {
    appendTurn(d)
  } else if (t === 'session.done') {
    doneInfo.value = `会话完成 · 时长 ${typeof d.duration_seconds === 'number' ? d.duration_seconds.toFixed(1) : d.duration_seconds}s`
    if (running.value) teardown(false)
  } else if (t === 'participant.reconnecting') {
    connText.value = '识别服务短暂波动 · 正在自动恢复'
  } else if (t === 'error') {
    hint.value = '服务端错误：' + (d.message || JSON.stringify(d).slice(0, 160))
  } else {
    dlog('克隆会话 EVT ' + JSON.stringify(d).slice(0, 180), 'evt')
  }
}

async function appendTurn(d) {
  const name = d.speaker_name || (d.role_index !== undefined ? `说话人 ${Number(d.role_index) + 1}` : '') || d.participant_id || '说话人'
  if (d.type === 'transcription.partial') {
    const key = d.segment_id ? 's:' + d.segment_id : 'p:' + (d.participant_id || 0)
    let row = turns.value.find(x => x.partial && x.key === key)
    if (!row) {
      row = { key, partial: true, name, text: d.text || '', time: nowStr(), speak: '' }
      turns.value.unshift(row)
    } else { row.text = d.text || ''; row.name = name }
  } else {
    const id = d.segment_id != null ? `${d.participant_id || d.role_index || ''}:${d.segment_id}` : null
    if (id && finalSegments.has(id)) return
    if (id) finalSegments.add(id)
    turns.value = turns.value.filter(x => !(x.partial && (x.key === 's:' + d.segment_id || x.key === 'p:' + (d.participant_id || 0))))
    const row = { key: 'f:' + (d.segment_id || Date.now()), partial: false, name,
      text: d.text || '', time: nowStr(), speak: 'pending', voice: voiceSel.value, model: ttsModel.value,
      audio: [], latency: 0, sizeKB: 0 }
    turns.value.unshift(row)
    if (row.text.trim() && !stopping) enqueueTTS(turns.value[0])
    else row.speak = 'skip'
  }
  await nextTick()
  if (listEl.value) listEl.value.scrollTo({ top: 0, behavior: d.type === 'transcription.partial' ? 'auto' : 'smooth' })
}

/* ---------- TTS 串行队列：final 依次「合成→播放」，互不重叠 ---------- */
function enqueueTTS(turn) {
  return speech.add(signal => runTTS(turn, signal)).catch(e => { turn.speak = 'error'; turn.errMsg = e.message })
}
async function runTTS(turn, signal) {
  if (signal.aborted) { turn.speak = 'skip'; return }
  turn.speak = 'synth'
  turn.audio = []; turn.sizeKB = 0
  const t0 = performance.now()
  try {
    for (const part of speechChunks(turn.text, TTS_MAX_CHARS)) {
      const blob = await synthesize(turn.voice, part, signal)
      if (signal.aborted) return
      turn.audio.push(blob)
      turn.latency = +((performance.now() - t0) / 1000).toFixed(1)
      turn.sizeKB += +(blob.size / 1024).toFixed(0)
      turn.speak = 'playing'
      if (!await playBlob(blob)) { turn.speak = 'skip'; return }
    }
    if (!signal.aborted) { turn.speak = 'done'; pruneAudio() }
  } catch (e) {
    if (signal.aborted) { turn.speak = 'skip'; return }
    turn.speak = 'error'
    turn.errMsg = e.message
    log(`克隆会话：合成失败（${e.message}）`, 'err')
  }
}
async function replay(turn) {
  if (!props.active || running.value || connecting.value) return
  output(); speech.reset()
  if (turn.speak === 'done' && turn.audio?.length) {
    try {
      await speech.add(async signal => {
        for (const blob of turn.audio) {
          if (signal.aborted || !await playBlob(blob)) return
        }
      })
    } catch (error) { turn.errMsg = error.message; turn.speak = 'error' }
  } else { turn.speak = 'pending'; await enqueueTTS(turn) }
}
function pruneAudio() {
  let bytes = 0
  for (const row of turns.value) {
    bytes += (row.audio || []).reduce((sum, blob) => sum + blob.size, 0)
    if (bytes > 20 * 1024 * 1024) row.audio = []
  }
}
function clearTurns() { turns.value = [] }
function speakLabel(s) {
  return { pending: '排队中…', synth: '合成中…', playing: '🔊 复述中…', done: '已复述', error: '合成失败', skip: '已跳过' }[s] || ''
}

/* ---------- 停止 ---------- */
async function stopSession() { await teardown(true) }
async function teardown(commit) {
  const signal = session.controller.signal, socket = ws
  connecting.value = false
  running.value = false; stopping = true
  speech.cancel()
  for (const turn of turns.value) if (['pending', 'synth', 'playing'].includes(turn.speak)) turn.speak = 'skip'
  clearInterval(clockTimer); clockTimer = null
  clearTimeout(micWatchTimer); micWatchTimer = null
  if (mic) { mic.stop(); mic = null }
  if (!commit || !sentFrames) { session.cancel(); closeSocket(socket); if (ws === socket) ws = null }
  meterW.value = 0
  hint.value = commit ? '正在完成最后片段…' : '会话已停止'
  connText.value = commit ? '正在收尾…' : '已停止'; connKind.value = 'idle'
  if (commit) log(`克隆会话：已结束（发送 ${sentFrames} 帧）`, 'evt')
  if (commit && sentFrames > 0) {
    const complete = await drainSocket(socket)
    if (!session.current(signal)) return
    session.cancel(); if (ws === socket) ws = null
    connText.value = '已停止'
    hint.value = complete ? '本轮转写已完成，播放已停止' : '识别收尾未完成，请核对最后一句。'
  }
}
function toggleMic() { (running.value || connecting.value) ? teardown(!connecting.value) : startSession() }
function suspend() {
  reference.cancel(); requests.cancel(); cloneBusy.value = false
  recMic?.stop(); recMic = null; clearInterval(recTimer)
  recBtnTxt.value = '录制参考音频'; recTimerTxt.value = ''
  teardown(false)
}

onMounted(() => { if (props.active && store.apiKey) listVoices() })
watch(() => props.active, active => { if (active && store.apiKey) listVoices() })
onBeforeUnmount(() => {
  sound?.dispose(); clearTurns()
  stopping = true
  if (recTimer) clearInterval(recTimer)
  if (recMic) recMic.stop()
  if (clockTimer) clearInterval(clockTimer)
  if (micWatchTimer) clearTimeout(micWatchTimer)
  if (mic) mic.stop()
  if (ws) { try { ws.close() } catch (e) { /* 忽略 */ } }
})
</script>

<template>
  <section class="vc">
    <header class="vc-top">
      <div class="vc-brand"><span class="dot"></span>声音克隆对话</div>
      <div class="vc-sub">你的声音，替我说话 —— 克隆音色注册 + 实时转写 + 克隆音色复述</div>
    </header>
    <div class="vc-grid">
      <!-- 左卡：克隆注册 -->
      <div class="vc-card vc-left">
        <h2>① 说话人1 · 克隆我的声音</h2>
        <div class="vc-note">参考录音：5–15 秒清晰的单人讲话。请仅使用本人或已获授权的声音。</div>
        <div class="vc-row">
          <button class="vc-btn" :class="{ rec: !!recTimerTxt }" @click="toggleRec()">{{ recBtnTxt }}</button>
          <span class="vc-timer">{{ recTimerTxt }}</span>
          <span class="vc-meta">{{ recInfo }}</span>
        </div>
        <div class="vc-row">
          <label class="vc-btn ghost">或选择文件
            <input type="file" accept="audio/*" style="display:none" ref="refFileInput" @change="onRefFileInput"></label>
        </div>
        <div class="vc-row">
          <input class="vc-input" v-model="voiceName" placeholder="音色名（英文/数字/下划线）">
          <button class="vc-btn primary" :disabled="cloneBusy" @click="cloneVoice()">{{ cloneBusy ? '注册中…' : '注册复刻音色' }}</button>
        </div>
        <div class="vc-meta wrap">{{ cloneResult }}</div>
        <div class="vc-sep"></div>
        <div class="vc-row">
          <select class="vc-input wide" v-model="voiceSel">
            <option value="" disabled>— 音色列表 —</option>
            <option v-for="v in voices" :key="v" :value="v">{{ v }}</option>
          </select>
          <button class="vc-btn mini" @click="listVoices()">刷新</button>
          <button class="vc-btn mini danger" @click="delVoice()">删除</button>
        </div>
        <div class="vc-row">
          <span class="vc-meta">合成后端</span>
          <span class="vc-meta dim">由当前语音服务提供</span>
        </div>
        <div class="vc-row">
          <input class="vc-input wide" v-model="probeText" placeholder="试听文本…">
          <button class="vc-btn" @click="probeSpeak()">试听</button>
        </div>
        <div class="vc-meta">{{ probeSt }} {{ voicesNote }}</div>
      </div>

      <!-- 右卡：实时变声会话 -->
      <div class="vc-card vc-right">
        <div class="vc-head">
          <h2>② 说话人2 · 用 TA 的声音说话</h2>
          <div class="vc-state">
            <span class="badge" :class="connKind">{{ connText }}</span>
            <span class="clock">{{ clock }}</span>
          </div>
        </div>
        <div class="vc-row ctrl">
          <button class="vc-mic" :class="{ on: running }" @click="toggleMic()">
            {{ connecting ? '取消连接' : running ? '■ 停止会话' : '🎤 开始对话' }}
          </button>
          <div class="vc-meter"><div class="bar" :style="{ width: meterW + '%' }"></div></div>
        </div>
        <div class="vc-hint">{{ hint }}</div>
        <div class="vc-list" ref="listEl">
          <p v-if="!turns.length" class="vc-empty">开始后，说出的话将实时转写，并以克隆音色逐句复述…</p>
          <div v-for="row in turns" :key="row.key" class="vc-turn" :class="{ partial: row.partial }">
            <div class="t-head">
              <span class="t-name">{{ row.name }}</span>
              <span class="t-time">{{ row.time }}</span>
            </div>
            <div class="t-text">{{ row.text }}</div>
            <div v-if="!row.partial && row.speak" class="t-speak" :class="row.speak">
              <span>{{ speakLabel(row.speak) }}</span>
              <span v-if="row.speak === 'done'" class="t-dim">{{ row.sizeKB }}KB · 合成 {{ row.latency }}s</span>
              <button v-if="['done', 'error', 'skip'].includes(row.speak)" type="button" class="t-replay" :disabled="running || connecting" @click="replay(row)">{{ row.speak === 'done' && row.audio?.length ? '重播' : '重新合成并播放' }}</button>
              <span v-if="row.speak === 'error'" class="t-dim">{{ row.errMsg }}</span>
            </div>
          </div>
        </div>
        <div v-if="doneInfo" class="vc-meta">{{ doneInfo }}</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.vc { max-width: 1180px; margin: 0 auto; padding: 18px 20px 40px; }
.vc-top { display: flex; align-items: baseline; gap: 14px; min-height: 44px; padding: 6px 0 14px; flex-wrap: wrap; }
.vc-brand { font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.vc-brand .dot { width: 10px; height: 10px; border-radius: 50%; background: #0e9488; }
.vc-sub { font-size: 13px; opacity: .7; }
.vc-grid { display: grid; grid-template-columns: 400px minmax(0, 1fr); gap: 18px; align-items: start; }
@media (max-width: 980px) { .vc-grid { grid-template-columns: 1fr; } }
.vc-card { background: var(--panel, #fff); border: 1px solid rgba(15, 23, 42, .09); border-radius: 14px; padding: 18px; box-shadow: 0 1px 3px rgba(15, 23, 42, .05); }
.vc-card h2 { font-size: 15px; font-weight: 700; margin: 0 0 8px; }
.vc-note { font-size: 12px; opacity: .65; margin-bottom: 12px; line-height: 1.5; }
.vc-sep { height: 1px; background: rgba(15, 23, 42, .08); margin: 14px 0; }
.vc-row { display: flex; align-items: center; gap: 10px; margin: 10px 0; flex-wrap: wrap; }
.vc-row.ctrl { gap: 14px; }
.vc-btn { border: 1px solid rgba(15, 23, 42, .18); background: #fff; color: #0f172a; border-radius: 9px; padding: 7px 14px; font-size: 13px; cursor: pointer; }
.vc-btn:hover { border-color: #0e9488; }
.vc-btn.primary { background: #0e9488; border-color: #0e9488; color: #fff; }
.vc-btn.primary:disabled { opacity: .6; cursor: wait; }
.vc-btn.ghost { display: inline-block; color: inherit; }
.vc-btn.mini { padding: 5px 10px; font-size: 12px; }
.vc-btn.mini.danger { color: #dc2626; }
.vc-btn.rec { background: #fee2e2; border-color: #ef4444; color: #b91c1c; }
.vc-input { border: 1px solid rgba(15, 23, 42, .18); border-radius: 9px; padding: 7px 10px; font-size: 13px; min-width: 0; flex: 0 1 auto; }
.vc-input.wide { flex: 1 1 160px; width: 100%; }
.vc-timer { font-variant-numeric: tabular-nums; font-size: 13px; color: #b91c1c; min-width: 52px; }
.vc-meta { font-size: 12px; opacity: .7; }
.vc-meta.dim { opacity: .5; }
.vc-meta.wrap { word-break: break-all; line-height: 1.5; }
.vc-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.vc-head h2 { margin: 0; }
.vc-state { display: flex; align-items: center; gap: 10px; }
.badge { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: rgba(15, 23, 42, .06); color: inherit; }
.badge.ready { background: #ccfbf1; color: #0f766e; }
.badge.connecting { background: #fef3c7; color: #b45309; }
.clock { font-variant-numeric: tabular-nums; font-size: 13px; opacity: .75; }
.vc-mic { border: none; border-radius: 10px; padding: 10px 22px; font-size: 15px; font-weight: 600; cursor: pointer; background: #0e9488; color: #fff; }
.vc-mic.on { background: #ef4444; }
.vc-meter { flex: 1; min-width: 80px; height: 8px; border-radius: 4px; background: rgba(15, 23, 42, .08); overflow: hidden; }
.vc-meter .bar { height: 100%; width: 0; background: linear-gradient(90deg, #14b8a6, #f59e0b); transition: width .1s linear; }
.vc-hint { font-size: 13px; color: #0f766e; background: #f0fdfa; border-radius: 8px; padding: 8px 12px; margin: 8px 0; line-height: 1.5; }
.vc-list { max-height: 58vh; overflow-y: auto; border: 1px solid rgba(15, 23, 42, .08); border-radius: 10px; padding: 10px; display: flex; flex-direction: column; gap: 10px; }
.vc-empty { font-size: 13px; opacity: .5; text-align: center; padding: 30px 0; margin: 0; }
.vc-turn { border: 1px solid rgba(15, 23, 42, .08); border-radius: 10px; padding: 10px 12px; background: #fff; }
.vc-turn.partial { opacity: .65; border-style: dashed; }
.t-head { display: flex; justify-content: space-between; font-size: 12px; opacity: .65; margin-bottom: 4px; }
.t-name { font-weight: 600; color: #0f766e; }
.t-text { font-size: 14px; line-height: 1.55; }
.vc-turn.partial .t-text { color: rgba(15, 23, 42, .6); }
.t-speak { display: flex; align-items: center; gap: 10px; margin-top: 8px; font-size: 12px; padding-top: 8px; border-top: 1px dashed rgba(15, 23, 42, .1); }
.t-speak.pending, .t-speak.synth { color: #b45309; }
.t-speak.playing { color: #0f766e; font-weight: 600; }
.t-speak.done { color: #047857; }
.t-speak.error, .t-speak.skip { color: #dc2626; }
.t-dim { opacity: .6; }
.t-replay { cursor: pointer; color: #0e9488; text-decoration: underline; }

</style>
