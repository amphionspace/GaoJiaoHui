<script setup>
/* 模块二：多人对话工作台 —— 完整复刻 https://portal.amphion.top/playground/target-dialogue
   （「多人对话翻译工作台」v20260910-scene-v2-1 的三栏工作台），按需求只对接两类接口：
   ① 声纹注册（HTTP）：GET/POST /speaker/v1/profiles、DELETE /speaker/v1/profiles/{id}、
      POST /auth/v1/ephemeral-tokens（一次性 JWT，失败退回 ?api_key= 直连）
   ② 流式转写（WSS）：/asr/v1/target-dialogue —— session.authenticate → session.update
      （participants 目标声纹 / filter open·targets_only / hotwords 热词）→ 二进制 PCM 帧
      → transcription.partial/final（说话人归属）、speaker.sample.progress（匿名采样 5s）、
      speaker.enroll（边聊边采集录入此人）、session.update 原地锁定 targets_only、session.done。
   与原页面的差异：裁掉翻译 / TTS 译音 / 声音情绪（分别走 qwen_text / qwen_realtime / e2v
   接口，不属于声纹注册与流式转写）；其余功能全部保留。
   浅色配色与模块一（未来手记旅程）一致（全局 styles.css 的 CSS 变量体系）。
   Gateway 留空 = 经本地服务 /proxy 同源转发（server/main.py）；填写 = 直连该网关。 */
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { WS_HOST } from '../core/api.js'
import { store, setApiKey, log, dlog } from '../core/store.js'
import { SR, Mic, wavEncode, fileToPCM } from '../core/audio.js'

const MAX_PROFILES = 4            // 目标声纹上限（同原页）
const MIN_ENROLL = 5              // 注册片段最小秒数（不足不保存/服务端补零同款规则）
const MAX_ENROLL = 10             // 录制自动停止秒数
const CLIP_SILENCE = 0.25         // 多段拼接时的段间静音秒数
const SESSION_MAX = 1800          // 会话时长上限（秒，与原页 30 分钟一致）
/* 说话人色板：原页暗色 8 色在白底偏浅，换同色系加深版本（amber/teal/violet/rose…） */
const ROLE_COLORS = ['#d97706', '#0e9488', '#7c3aed', '#e11d48', '#4d7c0f', '#2563eb', '#a16207', '#c026d3']

/* ---------- 连接面板（同原页 auth-panel） ---------- */
const gateway = ref(localStorage.getItem('amphion_gateway') || '')
const remember = ref(localStorage.getItem('amphion_remember') !== '0')
const keyInput = ref(store.apiKey)
const connText = ref('未连接')
const connKind = ref('idle')                  // idle | ready | error
watch(() => store.apiKey, k => { keyInput.value = k })   // 顶栏改 Key 时保持同步

function httpBase() { return gateway.value.trim().replace(/\/+$/, '') || '/proxy' }
function wsBase() {
  const g = gateway.value.trim().replace(/\/+$/, '')
  return g ? g.replace(/^http/i, 'ws') : WS_HOST
}
function saveConnection() {
  if (remember.value) localStorage.setItem('amphion_gateway', gateway.value.trim())
  else localStorage.removeItem('amphion_gateway')
  localStorage.setItem('amphion_remember', remember.value ? '1' : '0')
}
function onKeyChange() { setApiKey(keyInput.value) }
function clearConnection() {
  gateway.value = ''; saveConnection(); keyInput.value = ''; setApiKey('')
  connText.value = '本机连接信息已清除'; connKind.value = 'idle'
  log('工作台：本机连接信息已清除')
}

/* HTTP：X-API-Key + /proxy 同源转发（或直连网关）；错误带 status 抛出 */
async function jfetch(path, opts = {}) {
  let r
  try {
    r = await fetch(httpBase() + path, { ...opts, headers: { 'X-API-Key': keyInput.value.trim(), ...(opts.headers || {}) } })
  } catch (e) {
    throw Object.assign(new Error('无法连接 Gateway：' + e.message), { status: 0 })
  }
  if (!r.ok) {
    let detail = 'HTTP ' + r.status
    try { const b = await r.json(); detail = b.detail || b.message || detail } catch (e) { /* 非 JSON 响应 */ }
    throw Object.assign(new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)), { status: r.status })
  }
  return r.status === 204 ? null : r.json()
}

async function connect() {                     // 「连接并读取声纹」按钮
  if (!keyInput.value.trim()) {
    showAlert('API KEY', '请先填写 API Key', '声纹接口与识别 WS 均需 API Key。',
      '在右侧粘贴 sk-... 开头的 Key，或使用页面顶栏输入框。')
    return
  }
  saveConnection()
  try {
    await loadProfiles()
    log('工作台：连接并读取声纹成功（' + profiles.value.length + ' 个）', 'ok')
  } catch (e) {
    connKind.value = 'error'; connText.value = '连接失败'
    showAlert('ERROR', '连接失败', e.message,
      gateway.value.trim() ? '直连网关需网关开放 CORS；默认建议留空，走本地 /proxy 转发。'
                           : '本地服务未启动？请先运行 python3 server/main.py（端口 8766）。')
  }
}

/* ---------- 错误横幅（原页同款） ---------- */
const alertBox = ref(null)                    // { label, title, message, hint }
function showAlert(label, title, message, hint) { alertBox.value = { label, title, message, hint } }
function dismissAlert() { alertBox.value = null }

/* ---------- 左栏：注册声纹（enrollment-stage，同原页） ---------- */
const clips = ref([])              // [{ id, label, pcm: Int16Array(16k) }]
const profileName = ref('')
const consent = ref(true)
const autoSelect = ref(true)
const enrollStatus = ref('保持单人、安静、距离稳定。')
const clipCount = computed(() => clips.value.length + ' 段')
const clipDuration = computed(() => {   // 累计时长（含段间静音，同原页口径）
  const s = clips.value.reduce((t, c) => t + c.pcm.length / SR, 0)
    + Math.max(0, clips.value.length - 1) * CLIP_SILENCE
  return `累计时长 ${s.toFixed(1)} 秒`
})
let idSeq = 0

/* 录制片段：10 秒倒计时自动停；手动停止不足 5 秒不保存；超长截断、过短补零（原页同款规则） */
const enrolling = ref(false)
const enrollBtnTxt = ref('开始录制')
let enrollResolve = null, enrollTickTimer = null, enrollAutoTimer = null, enrollStartedAt = 0

async function recordClip() {
  if (enrolling.value) { enrollResolve && enrollResolve('manual'); return }
  const mic = new Mic()
  const chunks = []
  enrolling.value = true; enrollBtnTxt.value = '正在打开麦克风…'
  enrollStatus.value = `可随时手动停止；不足 ${MIN_ENROLL} 秒不会保存，${MAX_ENROLL} 秒自动停止。`
  try {
    await mic.start(() => {}, f => chunks.push(f))       // collect 模式：仅收集不出帧
    enrollStartedAt = performance.now()
    const tick = () => {
      const s = (performance.now() - enrollStartedAt) / 1000
      enrollBtnTxt.value = `停止录制 · ${Math.max(0, Math.ceil(MAX_ENROLL - s))} 秒`
    }
    tick()
    const reason = await new Promise(resolve => {
      enrollResolve = resolve
      enrollTickTimer = setInterval(tick, 200)
      enrollAutoTimer = setTimeout(() => resolve('auto'), MAX_ENROLL * 1000)
    })
    if (reason === 'manual') {
      const s = (performance.now() - enrollStartedAt) / 1000
      if (s < MIN_ENROLL) {
        enrollStatus.value = `已手动停止；录音只有 ${s.toFixed(1)} 秒，不足 ${MIN_ENROLL} 秒，未加入片段。`
        return
      }
    }
    const len = chunks.reduce((t, c) => t + c.length, 0)
    const joined = new Int16Array(len)
    let off = 0; for (const c of chunks) { joined.set(c, off); off += c.length }
    let bounded = joined.subarray(0, SR * MAX_ENROLL)          // 超长截到 10s
    if (bounded.length < SR * MIN_ENROLL) {                    // 过短补零到 5s（服务端最小样本）
      const padded = new Int16Array(SR * MIN_ENROLL)
      padded.set(bounded); bounded = padded
    }
    appendClip(bounded, `麦克风录音 ${clips.value.length + 1}`)
    enrollStatus.value = reason === 'auto'
      ? `已录满 ${MAX_ENROLL} 秒并自动停止，可点击播放检查。`
      : '已手动停止并添加录音，可点击播放检查。'
  } catch (e) {
    enrollStatus.value = e.message
    showAlert('ERROR', '添加录音失败', e.message, '可改用「添加音频」上传本地音频文件注册。')
  } finally {
    mic.stop()
    clearInterval(enrollTickTimer); clearTimeout(enrollAutoTimer); enrollResolve = null
    enrolling.value = false; enrollBtnTxt.value = '开始录制'
  }
}

function appendClip(pcm, label) { clips.value.push({ id: 'clip-' + (++idSeq), label, pcm }) }

/* 添加音频文件（可多选；需先勾选授权） */
async function onEnrollFiles(e) {
  const files = [...(e.target.files || [])]
  e.target.value = ''
  try {
    if (!consent.value) throw new Error('请先确认已取得本人授权')
    for (const f of files) appendClip(await fileToPCM(f), f.name)
    enrollStatus.value = '音频片段已添加，可继续添加或创建档案。'
  } catch (err) {
    enrollStatus.value = err.message
    showAlert('ERROR', '添加音频失败', err.message, '支持常见音频格式，自动转 16 kHz 单声道。')
  }
}

/* 片段播放（▶/■ 切换，16k AudioContext） */
const playingClipId = ref(null)
let playCtx = null, playNode = null
function stopClipPlay() {
  try { playNode && playNode.stop() } catch (e) { /* 已停止 */ }
  playNode = null; playingClipId.value = null
}
async function toggleClip(i) {
  const c = clips.value[i]; if (!c) return
  if (playingClipId.value === c.id) { stopClipPlay(); return }
  stopClipPlay()
  playCtx = playCtx && playCtx.state !== 'closed' ? playCtx : new (window.AudioContext || window.webkitAudioContext)()
  await playCtx.resume()
  const buf = playCtx.createBuffer(1, c.pcm.length, SR)
  const ch = buf.getChannelData(0)
  for (let j = 0; j < c.pcm.length; j++) ch[j] = c.pcm[j] / 32768
  playNode = playCtx.createBufferSource()
  playNode.buffer = buf; playNode.connect(playCtx.destination)
  playingClipId.value = c.id
  playNode.onended = () => { if (playingClipId.value === c.id) stopClipPlay() }
  playNode.start()
}
function removeClip(i) {
  const c = clips.value[i]
  if (c && c.id === playingClipId.value) stopClipPlay()
  clips.value.splice(i, 1)
}
function clearClips() { stopClipPlay(); clips.value = [] }

/* 多段拼接（段间 0.25s 静音）→ WAV → POST multipart 注册（display_name / consent / audio） */
const creating = ref(false)
function concatClips() {
  const gap = Math.round(SR * CLIP_SILENCE)
  const total = clips.value.reduce((t, c) => t + c.pcm.length, 0) + Math.max(0, clips.value.length - 1) * gap
  const joined = new Int16Array(total)
  let off = 0
  clips.value.forEach((c, i) => {
    joined.set(c.pcm, off); off += c.pcm.length
    if (i < clips.value.length - 1) off += gap
  })
  return joined
}
async function createProfile() {
  try {
    if (!keyInput.value.trim()) throw new Error('请先填写 API Key')
    const name = profileName.value.trim()
    if (!name) throw new Error('请填写声纹档案名')
    if (!consent.value) throw new Error('请先确认已取得本人授权')
    if (!clips.value.length) throw new Error('请至少添加一段目标人的语音')
    creating.value = true
    enrollStatus.value = `正在提交 ${clips.value.length} 段语句并生成声纹…`
    const form = new FormData()
    form.append('display_name', name)
    form.append('consent', 'true')                        // 合规：服务器记录 consent_recorded_at
    form.append('audio', wavEncode([concatClips()]), 'enrollment-multi-utterance.wav')
    const created = await jfetch('/speaker/v1/profiles', { method: 'POST', body: form })
    const wants = autoSelect.value && !ambient.value
    const can = wants && selectedIds.value.length < MAX_PROFILES
    stopClipPlay(); clips.value = []; profileName.value = ''
    enrollStatus.value = can ? `已创建“${created.display_name}”，并加入本次识别。`
      : wants ? `已创建“${created.display_name}”；本次已选满 ${MAX_PROFILES} 人，未自动加入。`
      : `已创建“${created.display_name}”，未加入本次识别。`
    log('工作台：声纹档案已创建 ' + (created.display_name || created.id), 'ok')
    await loadProfiles(can ? created.id : null)
  } catch (e) {
    enrollStatus.value = e.message
    showAlert('ERROR', '创建声纹失败', e.message, '请检查 API Key 与音频时长（每段 5–10 秒），稍后重试。')
  } finally { creating.value = false }
}

/* ---------- 右栏：声纹管理（management-stage） ---------- */
const profiles = ref([])           // [{ id, display_name, status, quality, created_at }]
const selectedIds = ref([])        // 已勾选为目标人的 profile id（顺序即勾选顺序）
const ambient = ref(false)         // 边聊边采集（open 模式：匿名分角色，满 5s 可录入命名）
let preAmbientSelected = []        // 开启边聊边采集前暂存的预选（关闭后还原，同原页）
let autoSelectPref = true          // 「创建后参与」在边聊边采集期间的暂存值

const readyProfiles = computed(() => profiles.value.filter(p => p.status === 'ready'))
const profileCount = computed(() => readyProfiles.value.length + ' 个')
const selectedCount = computed(() => selectedIds.value.length + ' / ' + MAX_PROFILES)
const selectedProfiles = computed(() =>   // 按勾选顺序取 ready 档案
  selectedIds.value.map(id => profiles.value.find(p => p.id === id)).filter(p => p && p.status === 'ready'))

function fmtDate(v) {
  try { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(v)) }
  catch (e) { return v || '时间未知' }
}
function profileDuration(p) {
  const q = (p && p.quality) || {}
  let v = Number(q.duration_sec ?? q.duration_seconds)
  if (!Number.isFinite(v) && Array.isArray(q.durations_sec))
    v = q.durations_sec.reduce((t, x) => t + Number(x || 0), 0)
  return Number.isFinite(v) ? v.toFixed(1) + ' 秒' : '时长由服务端校验'
}

async function loadProfiles(selectId = null) {
  connText.value = '正在读取声纹…'; connKind.value = 'idle'
  const payload = await jfetch('/speaker/v1/profiles')
  profiles.value = payload.data || []
  if (selectId && !ambient.value && !selectedIds.value.includes(selectId)
      && selectedIds.value.length < MAX_PROFILES) selectedIds.value.push(selectId)
  connKind.value = 'ready'
  connText.value = `已连接 · ${profiles.value.length} 个声纹`
  updateIdleHint()
}
async function refreshProfiles() {
  try { await loadProfiles() } catch (e) { showAlert('ERROR', '刷新声纹失败', e.message, '可稍后重试，或检查 API Key。') }
}
function toggleProfile(p) {
  if (running.value || ambient.value) {
    showAlert('BUSY', running.value ? '会话进行中不能更改声纹分支' : '边聊边采集使用匿名角色',
      running.value ? '请先结束本轮识别再调整目标人。' : '边聊边采集开启时不使用预选声纹，将按匿名角色分离。',
      running.value ? '结束本轮后即可重新勾选。' : '关闭「边聊边采集」即可恢复预选。')
    return
  }
  const i = selectedIds.value.indexOf(p.id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else if (selectedIds.value.length >= MAX_PROFILES) {
    showAlert('LIMIT', `每次最多选择 ${MAX_PROFILES} 个声纹档案`, '已达目标人上限。',
      '可先取消勾选其他人，或删除不再使用的档案。')
  } else selectedIds.value.push(p.id)
  updateIdleHint()
}
async function deleteProfile(p) {
  if (running.value) { showAlert('BUSY', '会话进行中不能删除声纹档案', '请先结束本轮识别。', '删除后该声纹将无法用于新会话。'); return }
  if (!window.confirm(`删除声纹档案“${p.display_name || p.id}”？删除后无法用于新会话。`)) return
  try {
    await jfetch('/speaker/v1/profiles/' + encodeURIComponent(p.id), { method: 'DELETE' })
    const i = selectedIds.value.indexOf(p.id); if (i >= 0) selectedIds.value.splice(i, 1)
    await loadProfiles()
    connText.value = '声纹档案已删除'
    log('工作台：声纹档案已删除 ' + (p.display_name || p.id), 'ok')
  } catch (e) { showAlert('ERROR', '删除声纹失败', e.message, '请稍后重试。') }
}

/* 边聊边采集：开启时取消预选并暂存；关闭时还原（ready 且不超上限，同原页） */
function onAmbientChange() {
  if (running.value) { ambient.value = !ambient.value; return }   // 会话中锁定开关
  if (ambient.value) {
    autoSelectPref = autoSelect.value; autoSelect.value = false
    preAmbientSelected = [...selectedIds.value]; selectedIds.value = []
    hint.value = '可直接开始；系统将匿名分角色并累计非重叠语音'
  } else {
    autoSelect.value = autoSelectPref
    const ready = new Set(readyProfiles.value.map(p => p.id))
    const restored = []
    for (const id of preAmbientSelected) if (ready.has(id) && restored.length < MAX_PROFILES) restored.push(id)
    selectedIds.value = restored
    preAmbientSelected = []
    updateIdleHint()
  }
}

/* 热词：内置行业词包 + 自定义（换行/逗号分隔、去重、≤100，对本轮全部目标的 ASR 生效） */
const builtinHotword = ref('')
const customHotword = ref('')
const hotwordTerms = computed(() => {
  const seen = new Set(), out = []
  for (const item of String(customHotword.value || '').split(/[\n,，]/)) {
    const t = item.trim()
    if (t && !seen.has(t)) { seen.add(t); out.push(t) }
  }
  return out
})
const hotwordSummary = computed(() => {
  const n = (builtinHotword.value ? 1 : 0) + hotwordTerms.value.length
  return n ? `已启用 ${n} 项` : '未启用'
})
function buildHotwords() {
  if (hotwordTerms.value.length > 100) throw new Error('自定义热词最多 100 个')
  return { builtin: builtinHotword.value ? [builtinHotword.value] : [], custom: hotwordTerms.value }
}

/* ---------- 中栏：实时会话（WS /asr/v1/target-dialogue） ---------- */
const running = ref(false)
const clock = ref('00:00')
const meterW = ref(0)
const hint = ref('选择声纹或开启边聊边采集后开始')
const turns = ref([])             // [{ key, pid, name, color, text, time, partial }] 最新在头部
const doneInfo = ref('')
const ambientRoles = ref([])      // [{ roleIndex, seconds, ready, enrolling, enrolled }]
const listEl = ref(null)
const hasResult = computed(() => turns.value.length > 0)

let ws = null, mic = null, startedAt = 0, clockTimer = null, sentFrames = 0, micWatchTimer = null
let filterMode = 'targets_only'   // open（边聊边采集）/ targets_only（只留注册人）
let sessionRevision = 1, micWarned = false, matchWarned = false
let sessionReadyResolve = null, sessionReadyReject = null
let participantNames = new Map(), participantColors = new Map()
let ambientEnrollments = new Map()   // request_id -> { roleIndex, displayName }

function nowStr() {
  const d = new Date(), p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function updateIdleHint() {
  if (running.value) return
  hint.value = selectedIds.value.length
    ? `已选择 ${selectedIds.value.length} 人，点击麦克风开始识别`
    : ambient.value ? '可直接开始；系统将匿名分角色并累计非重叠语音' : '选择声纹或开启边聊边采集后开始'
}

/* 目标分支预览 chips（同原页 branch-preview：已选声纹 / 匿名角色采样进度+录入按钮） */
const branchChips = computed(() => {
  const chips = []
  if (running.value && filterMode === 'open') {
    for (const r of [...ambientRoles.value].sort((a, b) => a.roleIndex - b.roleIndex)) {
      const action = r.enrolled ? '已录入' : r.enrolling ? '录入中…'
        : r.ready ? 'ENROLL' : `${Number(r.seconds || 0).toFixed(1)}/5 秒`
      chips.push({ color: ROLE_COLORS[r.roleIndex % ROLE_COLORS.length], text: `说话人 ${r.roleIndex + 1} · ${action}`, roleIndex: r.roleIndex, action })
    }
  } else if (running.value) {
    for (const [pid, name] of participantNames.entries())
      chips.push({ color: participantColors.get(pid) || ROLE_COLORS[0], text: name })
  } else if (!ambient.value) {
    selectedProfiles.value.forEach((p, i) =>
      chips.push({ color: ROLE_COLORS[i % ROLE_COLORS.length], text: p.display_name }))
  }
  if (!chips.length && ambient.value && !running.value)
    chips.push({ color: 'var(--dim)', text: '开放采集 · 无需预选' })
  return chips
})
const showLock = computed(() => running.value && filterMode === 'open')
const lockDisabled = computed(() => participantNames.size === 0 || ambientEnrollments.size > 0)

async function startSession() {
  try {
    dismissAlert()
    if (enrolling.value) throw new Error('请先手动停止或等待声纹录音自动结束')
    if (!keyInput.value.trim()) throw new Error('请先填写 API Key')
    const ambientMode = ambient.value
    const selected = selectedProfiles.value
    if (!selected.length && !ambientMode) throw new Error('请选择声纹，或开启“边聊边采集”')
    stopClipPlay()
    turns.value = []; doneInfo.value = ''; ambientRoles.value = []
    ambientEnrollments.clear(); participantNames.clear(); participantColors.clear()
    sentFrames = 0; sessionRevision = 1; micWarned = matchWarned = false
    filterMode = ambientMode ? 'open' : 'targets_only'
    const hotwords = buildHotwords()

    const participants = selected.map((p, i) => ({
      id: `speaker_${i + 1}`,
      profile_id: p.id,
      source_language: 'auto',
      translation: { enabled: false, plugin: 'qwen_text' },
      tts: { enabled: false, plugin: 'qwen_realtime', voice_gender: 'female' },
      emotion: { enabled: false, plugin: 'e2v_audio' },
    }))
    participants.forEach((pt, i) => {
      participantNames.set(pt.id, selected[i].display_name)
      participantColors.set(pt.id, ROLE_COLORS[i % ROLE_COLORS.length])
    })

    /* 一次性 JWT 优先（浏览器免长期 Key），失败退回 ?api_key= 直连 */
    let token = null
    try {
      token = await jfetch('/auth/v1/ephemeral-tokens', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resource: 'asr.target_dialogue', expires_in_seconds: 60, max_session_seconds: SESSION_MAX }),
      })
    } catch (e) { dlog('工作台：token 签发失败（' + e.message + '），退回 ?api_key= 直连', 'evt') }

    connText.value = ambientMode ? '正在建立匿名角色分离…' : `正在建立 ${participants.length} 路声纹分支…`
    connKind.value = 'idle'
    const sock = new WebSocket(`${wsBase()}/asr/v1/target-dialogue${token ? '' : '?api_key=' + encodeURIComponent(keyInput.value.trim())}`)
    sock.binaryType = 'arraybuffer'
    ws = sock
    await new Promise((resolve, reject) => {
      sock.onopen = resolve
      sock.onerror = () => reject(new Error('WebSocket 连接失败（网关不可达或 Key 无效）'))
    })
    sock.onmessage = ev => { try { handleEvent(ev) } catch (e) { showAlert('ERROR', '处理事件失败', e.message, '可继续对话；若持续出现请结束本轮重开。') } }
    const sessionReady = new Promise((resolve, reject) => {
      const to = setTimeout(() => reject(new Error('多路声纹识别链路准备超时')), 30000)
      sessionReadyResolve = () => { clearTimeout(to); resolve() }
      sessionReadyReject = err => { clearTimeout(to); reject(err) }
    })
    sock.onclose = ev => {
      sessionReadyReject && sessionReadyReject(new Error('WebSocket 在链路就绪前关闭'))
      if (running.value) {
        if (ev.code === 4002) showAlert('BILLING', '余额不足，连接被关闭（4002）', 'WS 建立时有余额预检。', '请到 portal.amphion.top 充值或更换 API Key。')
        else if (ev.code !== 1000) showAlert('WS', `连接关闭（code ${ev.code}）`, '识别链路意外中断。', '可点击麦克风重新开始。')
        teardown(false)
      }
    }
    if (token) sock.send(JSON.stringify({ type: 'session.authenticate', access_token: token.access_token }))
    sock.send(JSON.stringify({
      type: 'session.update',
      session: {
        participants,
        filter: { mode: filterMode },
        hotwords,
        audio: { format: 'pcm_s16le', sample_rate_hz: SR, channels: 1 },
        recognition: { mode: 'role_separation', response_speed: 'balanced' },
      },
    }))
    try { await sessionReady } catch (e) { try { sock.close() } catch (err) { /* 忽略 */ } throw e }

    /* 麦克风：16k Int16 帧 → RMS 电平 + 二进制/JSON base64 发送 */
    running.value = true; startedAt = Date.now()
    meterW.value = 0
    mic = new Mic()
    await mic.start(frame => {
      if (!running.value || sock.readyState !== 1) return
      sentFrames++
      let sum = 0
      for (let i = 0; i < frame.length; i += 16) sum += frame[i] * frame[i]
      meterW.value = Math.min(100, Math.sqrt(sum / Math.ceil(frame.length / 16)) / 32768 * 260)
      /* 网关 target-dialogue 支持二进制 PCM 帧（同原页/旧实现，已实测两条路均通，统一走二进制） */
      sock.send(new Uint8Array(frame.buffer, frame.byteOffset, frame.byteLength))
    })
    micWatchTimer = setTimeout(() => {           // 3 秒零帧：输入被系统静音 / 自动播放策略暂停了采集
      if (running.value && sentFrames === 0 && !micWarned) {
        micWarned = true
        hint.value = '麦克风 3 秒内未采集到音频——请检查系统输入设备与浏览器权限（地址栏左侧图标），或换 Chrome 重试'
        log('工作台：麦克风零帧（AudioContext 可能被暂停或输入被静音）', 'err')
      }
    }, 3000)
    clockTimer = setInterval(() => {
      const s = Math.floor((Date.now() - startedAt) / 1000)
      clock.value = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
      /* targets_only 长时间无输出：最常见原因是说话人不是注册声纹本人（服务端按设计过滤旁人语句） */
      if (!matchWarned && filterMode === 'targets_only' && sentFrames > 150 && !turns.value.length) {
        matchWarned = true
        hint.value = `已采集约 ${Math.round(sentFrames * 0.128)} 秒音频，但尚未匹配到目标声纹——请确认说话人为注册本人（旁人语句不会显示），或停止后改用「边聊边采集」`
      }
    }, 250)
    hint.value = ambientMode
      ? '开放识别中 · 正常对话即可累计各角色的非重叠语音'
      : `正在进行角色分离并匹配 ${participants.length} 个目标声纹`
    connText.value = '会话进行中'; connKind.value = 'ready'
    log(`工作台：识别会话开始（${ambientMode ? 'open 匿名分离' : 'targets_only ' + participants.length + ' 人'}${hotwords.custom.length || hotwords.builtin.length ? ' · 热词已启用' : ''}）`, 'ok')
  } catch (e) {
    showAlert('ERROR', '启动识别失败', e.message,
      '常见原因：未选目标声纹、API Key 无效、余额不足（4002）或网关维护中。')
    if (mic) { mic.stop(); mic = null }
    if (ws) { try { ws.close() } catch (err) { /* 忽略 */ }; ws = null }
    running.value = false
  }
}

/* ---------- WS 事件分发（协议同原页 target-dialogue） ---------- */
function handleEvent(ev) {
  if (typeof ev.data !== 'string') return            // 本模块未启用译音音频流
  const d = JSON.parse(ev.data)
  const t = d.type || ''
  if (t === 'session.created') {
    sessionRevision = Number(d.revision || 1)
    filterMode = (d.filter && d.filter.mode) || filterMode
    hint.value = filterMode === 'open'
      ? '开放识别已就绪；将按匿名角色累计非重叠语音'
      : `正在匹配 ${(d.participants || []).length} 个目标声纹，旁人语句不会显示`
    sessionReadyResolve && sessionReadyResolve()
    sessionReadyResolve = sessionReadyReject = null
  } else if (t === 'session.updated' && d.update === 'participants') {
    sessionRevision = Number(d.revision || sessionRevision)
    filterMode = (d.filter && d.filter.mode) || filterMode
    if (filterMode === 'targets_only') {             // 原地锁定成功
      ambient.value = false
      autoSelect.value = autoSelectPref
      turns.value = turns.value.filter(x => !(x.partial && x.provisional))
      hint.value = `已原地上锁 · ${(d.bindings || []).length} 个角色已绑定，旁人内容将被过滤`
      connText.value = '会话已上锁'
    }
  } else if (t === 'speaker.identified') {
    const sim = Number(d.similarity)
    hint.value = `${d.speaker_name || d.participant_id} 声纹已确认${Number.isFinite(sim) ? ` · 相似度 ${sim.toFixed(3)}` : ''}`
  } else if (t === 'speaker.sample.progress') {      // 边聊边采集：匿名角色可用语音累计（满 5s 可录入）
    const idx = Number(d.role_index)
    const list = [...ambientRoles.value]
    const row = list.find(r => r.roleIndex === idx)
      || list[list.push({ roleIndex: idx, seconds: 0, ready: false, enrolling: false, enrolled: false }) - 1]
    row.seconds = Number(d.usable_seconds || 0)
    row.ready = d.ready === true
    if (d.accepted === false && !row.ready) row.rejected = true; else row.rejected = false
    ambientRoles.value = list
  } else if (t === 'speaker.enroll.started') {
    const p = ambientEnrollments.get(d.request_id)
    if (p) hint.value = d.pending ? `“${p.displayName}”仍在录入中；对话可以继续` : `服务端正在为“${p.displayName}”创建声纹；对话可以继续`
  } else if (t === 'speaker.enrolled') {             // 录入成功：档案入列、自动选为目标、说话人更名换色
    sessionRevision = Number(d.revision || sessionRevision)
    const pending = ambientEnrollments.get(d.request_id)
    ambientEnrollments.delete(d.request_id)
    const idx = Number(d.role_index)
    const list = [...ambientRoles.value]
    const row = list.find(r => r.roleIndex === idx)
    if (row) { row.enrolling = false; row.enrolled = true }
    ambientRoles.value = list
    if (d.profile && d.profile.id) {
      profiles.value = [d.profile, ...profiles.value.filter(p => p.id !== d.profile.id)]
      if (selectedIds.value.length < MAX_PROFILES && !selectedIds.value.includes(d.profile.id))
        selectedIds.value.push(d.profile.id)
    }
    if (d.participant && d.participant.id) {
      participantNames.set(d.participant.id, (d.profile && d.profile.display_name) || d.participant.speaker_name || `说话人 ${idx + 1}`)
      participantColors.set(d.participant.id, ROLE_COLORS[idx % ROLE_COLORS.length])
    }
    hint.value = `“${(d.profile && d.profile.display_name) || '说话人'}”已录入；可继续录入其他人，完成后点击“锁定目标”`
    log('工作台：边聊边采集已录入 ' + ((d.profile && d.profile.display_name) || ''), 'ok')
  } else if (t === 'speaker.enroll.error') {
    const pending = ambientEnrollments.get(d.request_id)
    if (pending) {
      const list = [...ambientRoles.value]
      const row = list.find(r => r.roleIndex === pending.roleIndex)
      if (row) row.enrolling = false
      ambientRoles.value = list
      ambientEnrollments.delete(d.request_id)
    }
    showAlert('ERROR', '声纹录入失败', d.message || '对话中声纹录入失败', '可稍后在「注册声纹」栏用录音/文件方式注册。')
  } else if (t === 'transcription.partial' || t === 'transcription.final') {
    appendTurn(d)
  } else if (t === 'session.done') {
    const s = d.duration_seconds
    doneInfo.value = `会话完成 · 时长 ${typeof s === 'number' ? s.toFixed(1) : s}s · 识别角色 ${d.identified_roles} · 压制 ${d.suppressed_roles}`
  } else if (t === 'participant.reconnecting') {
    connText.value = '识别服务短暂波动 · 正在自动恢复'
  } else if (t === 'error') {
    showAlert('ERROR', '服务端错误', d.message || JSON.stringify(d).slice(0, 200), '若持续出现请结束本轮后重开。')
  } else {
    dlog('工作台 EVT ' + JSON.stringify(d).slice(0, 220), 'evt')
  }
}

/* turn 行：partial 占位（segment_id 优先，否则按 participant）→ final 固化替换；最新优先 */
function speakerLabel(d) {
  return d.speaker_name || participantNames.get(d.participant_id)
    || (d.role_index !== undefined ? `说话人 ${Number(d.role_index) + 1}` : '') || d.participant_id || '未知说话人'
}
async function appendTurn(d) {
  if (matchWarned) {                        /* 之前提示过“未匹配到目标声纹”，现已出转写 → 恢复正常状态提示 */
    matchWarned = false
    hint.value = filterMode === 'open' ? '开放识别中 · 正常对话即可累计各角色的非重叠语音' : '已匹配目标声纹 · 正在实时转写'
  }
  const name = speakerLabel(d)
  const color = participantColors.get(d.participant_id) || ROLE_COLORS[Number(d.role_index || 0) % ROLE_COLORS.length]
  if (d.type === 'transcription.partial') {
    const key = d.segment_id ? 's:' + d.segment_id : 'p:' + d.participant_id
    let row = turns.value.find(x => x.partial && x.key === key)
    if (!row) {
      row = { key, pid: d.participant_id, partial: true, provisional: d.provisional === true, name, color, text: '', time: nowStr() }
      turns.value.unshift(row)
    } else { row.text = d.text || ''; row.name = name; row.color = color }
  } else {
    turns.value = turns.value.filter(x => !(x.partial && (x.key === 's:' + d.segment_id || x.pid === d.participant_id)))
    turns.value.unshift({ key: 'f:' + (d.segment_id || Date.now()), pid: d.participant_id, partial: false, provisional: false, name, color, text: d.text || '', time: nowStr() })
  }
  await nextTick()
  if (listEl.value) listEl.value.scrollTo({ top: 0, behavior: d.type === 'transcription.partial' ? 'auto' : 'smooth' })
}

/* 边聊边采集：为匿名角色命名 → speaker.enroll（对话不中断，服务端用已累计采样建档） */
function enrollAmbientRole(roleIndex) {
  try {
    if (!running.value || filterMode !== 'open' || !ws || ws.readyState !== 1)
      throw new Error('当前会话不在边聊边采集模式')
    if (!consent.value) throw new Error('请先在左栏勾选“已获得本人明确授权”')
    const role = ambientRoles.value.find(r => r.roleIndex === roleIndex)
    if (!role || !role.ready) throw new Error(`说话人 ${roleIndex + 1} 的有效单人语音尚未达到 5 秒`)
    if (role.enrolling || role.enrolled) return
    const displayName = window.prompt(`为“说话人 ${roleIndex + 1}”填写声纹档案名`, `说话人 ${roleIndex + 1}`)?.trim()
    if (!displayName) return
    const requestId = `ambient-${Date.now()}-${Math.random().toString(16).slice(2)}`
    const list = [...ambientRoles.value]
    const row = list.find(r => r.roleIndex === roleIndex)
    row.enrolling = true
    ambientRoles.value = list
    ambientEnrollments.set(requestId, { roleIndex, displayName })
    hint.value = `正在为“${displayName}”创建声纹；对话可以继续`
    ws.send(JSON.stringify({
      type: 'speaker.enroll',
      request_id: requestId,
      role_index: roleIndex,
      display_name: displayName,
      consent: true,
      participant: {
        id: `speaker_role_${roleIndex + 1}`,
        source_language: 'auto',
        translation: { enabled: false, plugin: 'qwen_text' },
        tts: { enabled: false, plugin: 'qwen_realtime', voice_gender: 'female' },
        emotion: { enabled: false, plugin: 'e2v_audio' },
      },
    }))
  } catch (e) {
    showAlert('ERROR', '声纹录入失败', e.message, '继续对话累计更多单人语音后再试。')
  }
}

/* 锁定目标：open 会话原地上锁为 targets_only（引擎不重启，已录入角色即刻生效） */
function lockTargets() {
  if (!running.value || filterMode !== 'open' || !ws || ws.readyState !== 1) return
  if (!participantNames.size) { showAlert('LOCK', '请先至少录入一个说话人', '锁定需要已录入的声纹角色。', '在上方分支预览中点击「录入此人」。'); return }
  sessionRevision += 1
  hint.value = '正在原会话上锁，识别引擎不会重启…'
  ws.send(JSON.stringify({ type: 'session.update', request_id: `lock-${Date.now()}`, revision: sessionRevision, session: { filter: { mode: 'targets_only' } } }))
}

/* 停止：发 commit 触发尾段 flush；open 会话结束后回落 targets_only（同原页） */
async function stopSession() { await teardown(true) }
async function teardown(commit) {
  if (!running.value && !mic && !ws) return
  running.value = false
  clearInterval(clockTimer); clockTimer = null
  clearTimeout(micWatchTimer); micWatchTimer = null
  if (mic) { mic.stop(); mic = null }
  if (filterMode === 'open') {          // 开放采集结束后：新注册档案已自动选中，可直接作为下轮目标
    ambient.value = false
    filterMode = 'targets_only'
    ambientRoles.value = []
    ambientEnrollments.clear()
    autoSelect.value = autoSelectPref
  }
  if (ws && ws.readyState === 1) {
    if (commit && sentFrames > 0) ws.send(JSON.stringify({ type: 'input_audio_buffer.commit' }))
    else ws.close()                     // 零音频帧不发 commit 直接关闭，避免服务端 "No audio data received."
  }
  if (commit && sentFrames === 0)
    showAlert('MIC', '本轮未采集到任何音频', '会话期间没有发出一帧音频，服务端不会返回转写。',
      '请检查麦克风权限与系统输入音量（浏览器地址栏左侧图标），或换 Chrome 重试。')
  meterW.value = 0
  hint.value = commit ? '正在完成各分支最后片段…' : '会话已停止'
  connText.value = commit ? '正在收尾…' : '已停止'
  updateIdleHint()
  if (commit) log('工作台：识别会话已结束（发送 ' + sentFrames + ' 帧）', 'evt')
}
function toggleMic() { running.value ? stopSession() : startSession() }

onBeforeUnmount(() => {
  if (enrollResolve) enrollResolve('manual')          // 结束可能还在进行的注册录音
  clearInterval(enrollTickTimer); clearTimeout(enrollAutoTimer)
  stopClipPlay()
  try { playCtx && playCtx.close() } catch (e) { /* 忽略 */ }
  clearInterval(clockTimer); clearTimeout(micWatchTimer)
  if (mic) mic.stop()
  if (ws) { ws.onclose = null; try { ws.close() } catch (e) { /* 忽略 */ } }
})
</script>

<template>
  <section class="wb">
    <div class="noise" aria-hidden="true"></div>
    <header class="topbar">
      <span class="brand"><span class="brand-mark">A</span><span>多人对话</span></span>
      <div class="header-actions">
        <a href="https://portal.amphion.top/docs/api/target_dialogue" target="_blank" rel="noopener">接入文档 ↗</a>
      </div>
    </header>

    <div v-if="alertBox" class="alert-banner" role="alert">
      <div class="alert-icon" aria-hidden="true">!</div>
      <div class="alert-content">
        <span class="alert-label">{{ alertBox.label }}</span>
        <strong>{{ alertBox.title }}</strong>
        <p>{{ alertBox.message }}</p>
        <small>{{ alertBox.hint }}</small>
      </div>
      <button class="alert-close" type="button" aria-label="关闭错误提示" @click="dismissAlert()">×</button>
    </div>

    <div class="stage-grid">
      <!-- 左栏：注册声纹 -->
      <article class="card stage enrollment-stage">
        <div class="stage-head">
          <h2>注册声纹</h2>
          <span class="counter">{{ clipCount }}</span>
        </div>
        <p class="stage-copy">同一人可录多段，每段 5–10 秒。</p>
        <label for="wb-name">声纹档案名</label>
        <input id="wb-name" v-model="profileName" placeholder="例如：接待员小陈 / Visitor Anna">
        <div class="enroll-actions">
          <button class="button ghost recording-btn" :class="{ recording: enrolling }" type="button" @click="recordClip()">{{ enrollBtnTxt }}</button>
          <label class="button ghost file-button" :class="{ disabled: enrolling }">添加音频
            <input type="file" accept="audio/*" multiple :disabled="enrolling" @change="onEnrollFiles"></label>
          <button class="button ghost" type="button" :disabled="enrolling" @click="clearClips()">清空片段</button>
        </div>
        <div class="clip-list">
          <div v-if="!clips.length" class="empty-small">尚未添加语句。可添加多段，每段保持 5–10 秒。</div>
          <div v-for="(c, i) in clips" :key="c.id" class="clip-row">
            <span class="clip-index">{{ String(i + 1).padStart(2, '0') }}</span>
            <div class="clip-main">
              <strong>{{ c.label }}</strong>
              <small>{{ (c.pcm.length / SR).toFixed(1) }} 秒 · 16 kHz mono</small>
            </div>
            <div class="clip-actions">
              <button class="icon-button" type="button" :disabled="enrolling"
                :aria-label="playingClipId === c.id ? '停止播放' : '播放该录音'" @click="toggleClip(i)">{{ playingClipId === c.id ? '■' : '▶' }}</button>
              <button class="icon-button danger" type="button" :disabled="enrolling" aria-label="删除该录音" @click="removeClip(i)">×</button>
            </div>
          </div>
        </div>
        <div class="clip-summary"><span>{{ clipDuration }}</span><span>每段 5–10 秒</span></div>
        <label class="consent"><input type="checkbox" v-model="consent"> 已获得本人明确授权，用于声纹身份识别</label>
        <label class="participation-option">
          <input type="checkbox" v-model="autoSelect" :disabled="ambient">
          <span><strong>创建后参与本次识别</strong><small>默认加入实时识别的目标声纹</small></span>
        </label>
        <button class="button primary wide" type="button" :disabled="creating" @click="createProfile()">{{ creating ? '正在创建…' : '创建声纹档案' }}</button>
        <small class="status-copy">{{ enrollStatus }}</small>
      </article>

      <!-- 中栏：实时对话 -->
      <div class="live-column card">
        <section class="results">
          <div class="results-head">
            <div>
              <h2>实时对话</h2>
              <div class="branch-preview">
                <template v-if="branchChips.length">
                  <span v-for="(chip, i) in branchChips" :key="i" :style="{ '--branch': chip.color }">{{ chip.text }}<button
                    v-if="chip.action === 'ENROLL'" class="enroll-role" type="button"
                    @click="enrollAmbientRole(chip.roleIndex)">录入此人</button></span>
                </template>
                <span v-else>等待选择目标人</span>
              </div>
            </div>
            <div class="live-meta">
              <span class="follow-state"><i></i>最新优先</span>
              <span class="timer">{{ clock }}</span>
            </div>
          </div>
          <div v-if="!hasResult" class="empty">选择目标声纹，或开启“边聊边采集”后直接开始。</div>
          <div ref="listEl" class="result-list">
            <article v-for="(t, i) in turns" :key="t.key" class="turn"
              :class="{ partial: t.partial, 'is-latest': i === 0 }" :style="{ '--accent': t.color }">
              <div class="turn-meta">
                {{ t.name }}
                <small><span>{{ t.partial ? '识别中' : '已确认' }}</span><time>{{ t.time }}</time></small>
              </div>
              <div class="turn-text"><p>{{ t.text }}</p></div>
            </article>
          </div>
          <div v-if="doneInfo" class="done-info">{{ doneInfo }}</div>
          <div class="session-dock">
            <div class="meter"><i :style="{ width: meterW + '%' }"></i></div>
            <p class="session-hint">{{ hint }}</p>
            <button class="mic" :class="{ live: running }" type="button" aria-label="开始或停止识别" @click="toggleMic()">
              <span class="mic-rings" aria-hidden="true"></span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
                <path d="M12 15a4 4 0 0 0 4-4V5a4 4 0 1 0-8 0v6a4 4 0 0 0 4 4Zm7-4a7 7 0 0 1-14 0M12 18v4m-4 0h8" /></svg>
            </button>
          </div>
        </section>
      </div>

      <!-- 右栏：连接 + 声纹管理 -->
      <aside class="side-column">
        <section class="auth-panel card">
          <div class="auth-head"><strong>连接</strong><span class="state" :class="connKind">{{ connText }}</span></div>
          <div class="gateway-field">
            <label for="wb-gateway">Gateway</label>
            <input id="wb-gateway" v-model="gateway" placeholder="本页可留空" autocomplete="off" spellcheck="false" @change="saveConnection">
            <small>留空时经本地服务 /proxy 同源转发；也可填 https://amphion.top 直连。</small>
          </div>
          <div>
            <label for="wb-key">API Key</label>
            <input id="wb-key" class="secret-input" v-model="keyInput" placeholder="sk-..." autocomplete="off" spellcheck="false" @change="onKeyChange">
          </div>
          <div class="local-credential-row">
            <label class="remember-connection"><input type="checkbox" v-model="remember"><span>本机记住连接</span></label>
            <button class="clear-connection" type="button" @click="clearConnection()">清除</button>
          </div>
          <button class="button secondary wide" type="button" @click="connect()">连接并读取声纹</button>
        </section>

        <article class="card stage management-stage">
          <div class="stage-head">
            <h2>声纹</h2>
            <div class="manage-tools">
              <span class="counter">{{ profileCount }}</span>
              <button class="icon-button" type="button" title="刷新" @click="refreshProfiles()">↻</button>
            </div>
          </div>
          <div class="selection-bar"><span>{{ selectionLabel }}</span><strong>{{ selectedCount }}</strong></div>
          <div class="ambient-bar">
            <label>
              <input type="checkbox" v-model="ambient" :disabled="running" @change="onAmbientChange">
              <span><strong>边聊边采集</strong><small>开启后不使用预选声纹；匿名分角色，达到 5 秒后录入并上锁</small></span>
            </label>
            <button v-if="showLock" class="lock-btn" type="button" :disabled="lockDisabled" @click="lockTargets()">锁定目标</button>
          </div>
          <details class="hotword-config">
            <summary><span>识别热词</span><small>{{ hotwordSummary }}</small></summary>
            <div class="hotword-fields">
              <label for="wb-builtin">内置行业词包</label>
              <select id="wb-builtin" v-model="builtinHotword">
                <option value="">不使用</option>
                <option value="finance">金融</option>
                <option value="education">教育</option>
                <option value="internet">互联网 / 技术</option>
              </select>
              <label for="wb-custom">自定义热词</label>
              <textarea id="wb-custom" rows="3" maxlength="6500" v-model="customHotword"
                placeholder="Amphion Gateway&#10;OpenTelemetry&#10;AUM"></textarea>
              <small>换行或逗号分隔；对本轮全部目标声纹的 ASR 生效。</small>
            </div>
          </details>
          <div class="profile-list" :class="{ 'selection-disabled': ambient }">
            <div v-if="!profiles.length" class="empty-small">连接后读取声纹档案。</div>
            <div v-for="p in profiles" :key="p.id" class="profile-row" :style="{
              '--profile-color': selectedIds.includes(p.id)
                ? ROLE_COLORS[selectedIds.indexOf(p.id) % ROLE_COLORS.length] : 'var(--line)' }">
              <input class="profile-enabled" type="checkbox" :checked="selectedIds.includes(p.id)"
                :disabled="running || ambient || p.status !== 'ready'" @change="toggleProfile(p)">
              <div class="profile-main">
                <strong>{{ p.display_name }}</strong>
                <small>{{ profileDuration(p) }}{{ p.status !== 'ready' ? ' · ' + p.status : '' }} · {{ fmtDate(p.created_at) }}</small>
              </div>
              <button class="icon-button danger delete-profile" type="button" title="删除档案" @click="deleteProfile(p)">×</button>
            </div>
          </div>
        </article>

        <article class="card stage info-stage">
          <div class="stage-head"><h2>接口</h2></div>
          <div class="spec"><span>声纹注册</span><code>POST /speaker/v1/profiles</code></div>
          <div class="spec"><span>声纹管理</span><code>GET · DELETE /speaker/v1/profiles</code></div>
          <div class="spec"><span>鉴权</span><code>POST /auth/v1/ephemeral-tokens</code></div>
          <div class="spec"><span>流式转写</span><code>WSS /asr/v1/target-dialogue</code></div>
          <div class="spec"><span>音频规格</span><code>16 kHz · s16le · 二进制帧</code></div>
        </article>
      </aside>
    </div>
  </section>
</template>

<style scoped>
/* ---- 基础骨架（布局复刻原页三栏工作台，配色走全局浅色变量体系） ---- */
.wb { position: relative; }
.wb .noise { position: absolute; inset: 0; pointer-events: none; opacity: .02; z-index: 0;
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2"/></filter><rect width="160" height="160" filter="url(%23n)"/></svg>'); }
.wb .topbar { position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between;
  gap: 14px; padding: 4px 2px 12px; min-height: 44px; }
.wb .brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; color: var(--text); }
.wb .brand-mark { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 9px;
  background: var(--acc); color: #fff; font-family: Georgia, serif; font-size: 16px; }
.wb .header-actions a { color: var(--acc); font-size: 12px; text-decoration: none; }
.wb .header-actions a:hover { text-decoration: underline; }

.wb .stage-grid { position: relative; z-index: 1; display: grid; grid-template-columns: 350px minmax(0, 1fr) 340px;
  gap: 14px; align-items: start; padding: 0 2px 4px; }
.wb .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; }
.wb .stage { padding: 16px; }
.wb .stage-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
.wb .stage h2 { font-family: Georgia, 'Songti SC', serif; font-weight: 400; margin: 0; font-size: 20px; color: var(--text); }
.wb .counter { color: var(--acc); background: rgba(47, 111, 237, .08); border-radius: 20px; padding: 5px 10px;
  font-size: 10px; white-space: nowrap; }
.wb .stage-copy { color: var(--dim); font-size: 11px; line-height: 1.7; margin: -6px 0 14px; }
.wb .empty-small { color: var(--dim); font-size: 11px; line-height: 1.7; padding: 14px 10px; text-align: center;
  border: 1px dashed var(--line); border-radius: 10px; margin: 10px 0; }
.wb .status-copy { display: block; color: var(--dim); font-size: 10px; line-height: 1.6; margin-top: 10px; }
.wb label { display: block; color: var(--dim); font-size: 11px; margin-bottom: 7px; }
.wb input, .wb select, .wb textarea { width: 100%; border: 1px solid var(--line); background: #fff; color: var(--text);
  border-radius: 8px; padding: 0 12px; height: 40px; outline: none; font: inherit; font-size: 13px; }
.wb textarea { padding: 9px 12px; height: auto; resize: vertical; line-height: 1.6; }
.wb input:focus, .wb select:focus, .wb textarea:focus { border-color: var(--acc); }
.wb .secret-input { font-family: ui-monospace, monospace; letter-spacing: .06em; }

.wb .button { min-height: 40px; padding: 0 14px; border-radius: 8px; border: none; background: var(--acc);
  color: #fff; font-weight: 600; cursor: pointer; font-size: 12px; }
.wb .button:hover { filter: brightness(1.05); }
.wb .button:disabled { opacity: .5; cursor: not-allowed; }
.wb .button.primary { width: 100%; min-height: 44px; font-size: 13px; margin-top: 4px; }
.wb .button.secondary { background: #fff; color: var(--text); border: 1px solid var(--line); }
.wb .button.secondary:hover { border-color: var(--acc); color: var(--acc); }
.wb .button.ghost { background: #fff; color: var(--text); border: 1px solid var(--line); }
.wb .button.ghost:hover { border-color: var(--acc); color: var(--acc); }
.wb .button.wide { width: 100%; }
.wb .icon-button { width: 28px; height: 28px; border-radius: 8px; border: 1px solid var(--line); background: #fff;
  color: var(--dim); cursor: pointer; display: grid; place-items: center; font-size: 13px; padding: 0; flex: 0 0 auto; }
.wb .icon-button:hover { border-color: var(--acc); color: var(--acc); }
.wb .icon-button.danger:hover { border-color: var(--err); color: var(--err); }

/* ---- 左栏：注册声纹 ---- */
.wb .enrollment-stage > label { margin-top: 4px; }
.wb .enroll-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 10px; }
.wb .file-button { position: relative; overflow: hidden; display: inline-flex; align-items: center; }
.wb .file-button input { position: absolute; inset: 0; opacity: 0; cursor: pointer; height: 100%; }
.wb .file-button.disabled { opacity: .5; pointer-events: none; }
.wb .recording-btn.recording { background: #fff; color: var(--err); border-color: var(--err); }
.wb .clip-list { border: 1px solid var(--line); border-radius: 10px; max-height: 190px; overflow-y: auto; }
.wb .clip-row { min-height: 54px; display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; gap: 8px;
  align-items: center; padding: 8px 10px; border-bottom: 1px solid var(--line); }
.wb .clip-row:last-child { border-bottom: 0; }
.wb .clip-index { color: var(--dim); font-family: ui-monospace, monospace; font-size: 11px; }
.wb .clip-main { min-width: 0; }
.wb .clip-main strong { display: block; font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb .clip-main small { display: block; color: var(--dim); font-size: 10px; margin-top: 3px; }
.wb .clip-actions { display: flex; gap: 6px; }
.wb .clip-summary { display: flex; justify-content: space-between; color: var(--dim); font-size: 10px; margin: 8px 2px 12px; }
.wb .consent, .wb .participation-option { display: flex; align-items: flex-start; gap: 8px; color: var(--dim);
  font-size: 11px; line-height: 1.5; cursor: pointer; margin: 0 0 10px; }
.wb .consent input, .wb .participation-option input { width: 14px; height: 14px; flex: 0 0 auto; padding: 0;
  margin-top: 2px; accent-color: var(--acc); }
.wb .participation-option strong { display: block; color: var(--text); font-size: 11px; }
.wb .participation-option small { display: block; margin-top: 2px; font-size: 10px; }
.wb .participation-option input:disabled { opacity: .4; }

/* ---- 中栏：实时对话（整页滚动布局下保持固定工作高度，滚动页面时停靠可视区） ---- */
.wb .live-column { display: flex; min-width: 0; overflow: hidden; position: sticky; top: 14px;
  height: calc(100vh - 140px); min-height: 480px; max-height: 660px; }
.wb .results { flex: 1; display: flex; flex-direction: column; min-width: 0; padding: 18px 20px 0; }
.wb .results h2 { font-size: 24px; }
.wb .results-head { display: flex; justify-content: space-between; align-items: center; gap: 14px; }
.wb .branch-preview { min-height: 24px; margin-top: 6px; display: flex; flex-wrap: wrap; gap: 5px; align-content: center; }
.wb .branch-preview span { border: 1px solid color-mix(in srgb, var(--branch, #9aa3ad) 45%, #fff);
  color: var(--branch, var(--dim)); border-radius: 20px; padding: 3px 9px; font-size: 10px;
  display: inline-flex; align-items: center; gap: 6px; }
.wb .branch-preview .enroll-role { min-height: 20px; padding: 0 8px; border: 0; border-radius: 20px;
  background: var(--acc); color: #fff; font-size: 10px; cursor: pointer; }
.wb .branch-preview .enroll-role:hover { filter: brightness(1.08); }
.wb .live-meta { display: flex; align-items: center; gap: 14px; flex: 0 0 auto; }
.wb .follow-state { display: inline-flex; align-items: center; gap: 6px; color: var(--dim); font-size: 10px; }
.wb .follow-state i { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
.wb .timer { color: var(--text); font-family: ui-monospace, monospace; font-size: 13px;
  background: var(--panel2); border-radius: 8px; padding: 5px 10px; }
.wb .empty { margin: 26px 0; text-align: center; color: var(--dim); font-size: 12px; line-height: 1.8; }
.wb .result-list { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 10px;
  padding: 14px 2px 10px; }
.wb .turn { position: relative; display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 14px;
  padding: 12px 14px 12px 18px; border-radius: 10px; background: #fff; border: 1px solid var(--line); }
.wb .turn::before { content: ''; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px;
  border-radius: 3px; background: var(--accent, var(--acc)); opacity: .5; }
.wb .turn.is-latest { border-color: color-mix(in srgb, var(--accent, var(--acc)) 38%, var(--line));
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent, var(--acc)) 6%, #fff), #fff 55%); }
.wb .turn.is-latest::before { opacity: 1; }
.wb .turn-meta { align-self: start; color: var(--accent, var(--acc)); font-size: 12px; font-weight: 700; line-height: 1.35;
  overflow-wrap: anywhere; }
.wb .turn-meta small { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; color: var(--dim);
  margin-top: 5px; font-size: 9px; font-weight: 400; letter-spacing: .08em; }
.wb .turn-meta time { color: var(--dim); font-family: ui-monospace, monospace; letter-spacing: 0; }
.wb .turn-text { min-width: 0; }
.wb .turn-text p { margin: 0; color: var(--text); line-height: 1.68; font-size: 15px; white-space: pre-wrap; overflow-wrap: anywhere; }
.wb .turn.partial .turn-text p { color: var(--dim); font-style: italic; }
.wb .turn.partial { opacity: .82; }
.wb .done-info { margin: 4px 0 10px; color: var(--ok); font-size: 11px; text-align: center; }
.wb .session-dock { position: relative; flex: 0 0 76px; padding: 8px 84px 0 0; border-top: 1px solid var(--line);
  background: var(--panel2); border-radius: 0 0 12px 12px; display: flex; align-items: center; }
.wb .meter { position: absolute; top: -1px; left: 0; right: 0; height: 3px; background: transparent; }
.wb .meter i { display: block; height: 100%; width: 0; border-radius: 3px;
  background: linear-gradient(90deg, var(--acc), var(--ok)); transition: width .1s linear; }
.wb .session-hint { margin: 0; color: var(--dim); font-size: 11px; line-height: 1.5; overflow: hidden;
  text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.wb .mic { position: absolute; right: 16px; top: -20px; width: 54px; height: 54px; border-radius: 50%;
  border: 1px solid var(--line); background: #fff; color: var(--text); cursor: pointer; display: grid; place-items: center;
  box-shadow: 0 6px 18px rgba(31, 36, 48, .12); transition: transform .15s ease; }
.wb .mic svg { width: 24px; height: 24px; }
.wb .mic:hover { transform: scale(1.06); }
.wb .mic.live { background: var(--acc); border-color: var(--acc); color: #fff; }
.wb .mic-rings { position: absolute; inset: -7px; border-radius: 50%; border: 2px solid var(--acc); opacity: 0; }
.wb .mic.live .mic-rings { animation: wb-ring 1.8s ease-out infinite; }
@keyframes wb-ring { 0% { transform: scale(.82); opacity: .5; } 100% { transform: scale(1.28); opacity: 0; } }

/* ---- 右栏：连接 + 声纹管理 ---- */
.wb .side-column { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.wb .auth-panel { padding: 16px; flex: 0 0 auto; }
.wb .auth-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; }
.wb .auth-head strong { font-size: 13px; }
.wb .state { font-size: 10px; border-radius: 20px; padding: 4px 9px; background: var(--panel2); color: var(--dim);
  max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb .state.ready { color: var(--ok); background: rgba(23, 138, 76, .08); }
.wb .state.error { color: var(--err); background: rgba(201, 49, 49, .08); }
.wb .gateway-field small { display: block; color: var(--dim); font-size: 10px; margin-top: 5px; line-height: 1.4; }
.wb .auth-panel > div { margin-bottom: 12px; }
.wb .local-credential-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.wb .remember-connection { display: inline-flex; align-items: center; gap: 7px; margin: 0; color: var(--dim);
  cursor: pointer; font-size: 11px; }
.wb .remember-connection input { width: 14px; height: 14px; flex: 0 0 auto; padding: 0; accent-color: var(--acc); }
.wb .clear-connection { padding: 0; border: 0; background: transparent; color: var(--dim); font-size: 10px; cursor: pointer; }
.wb .clear-connection:hover { color: var(--err); }

.wb .management-stage { flex: 1; display: flex; flex-direction: column; min-height: 220px; }
.wb .manage-tools { display: flex; align-items: center; gap: 8px; }
.wb .selection-bar { display: flex; justify-content: space-between; align-items: center; padding: 9px 12px;
  border: 1px solid var(--line); border-radius: 10px 10px 0 0; background: var(--panel2); color: var(--dim); font-size: 10px; }
.wb .selection-bar strong { color: var(--acc); font-size: 11px; }
.wb .ambient-bar { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;
  padding: 10px 12px; border: 1px solid var(--line); border-top: 0; }
.wb .ambient-bar label { display: flex; align-items: flex-start; gap: 8px; min-width: 0; margin: 0; cursor: pointer; }
.wb .ambient-bar input { width: 14px; height: 14px; flex: 0 0 auto; margin-top: 1px; accent-color: var(--acc); }
.wb .ambient-bar strong { display: block; color: var(--text); font-size: 11px; }
.wb .ambient-bar small { display: block; margin-top: 2px; color: var(--dim); font-size: 9px; line-height: 1.4; }
.wb .ambient-bar input:disabled { cursor: not-allowed; }
.wb .lock-btn { min-height: 30px; padding: 0 12px; border: 0; border-radius: 8px; background: var(--acc);
  color: #fff; font-size: 11px; font-weight: 600; cursor: pointer; flex: 0 0 auto; }
.wb .lock-btn:disabled { opacity: .4; cursor: not-allowed; }
.wb .hotword-config { flex: 0 0 auto; border: 1px solid var(--line); border-top: 0; }
.wb .hotword-config summary { display: flex; align-items: center; justify-content: space-between; gap: 10px;
  min-height: 36px; padding: 0 12px; color: var(--dim); font-size: 11px; cursor: pointer; list-style: none; }
.wb .hotword-config summary::-webkit-details-marker { display: none; }
.wb .hotword-config summary::before { content: '›'; color: var(--dim); font-size: 15px; transform: rotate(0); transition: transform .15s ease; }
.wb .hotword-config[open] summary::before { transform: rotate(90deg); }
.wb .hotword-config summary small { color: var(--acc); font-size: 9px; }
.wb .hotword-fields { display: grid; gap: 6px; padding: 2px 12px 12px; border-top: 1px solid var(--line); }
.wb .hotword-fields label { margin: 6px 0 -1px; }
.wb .hotword-fields select { height: 36px; font-size: 12px; }
.wb .hotword-fields textarea { min-height: 60px; font-size: 11px; }
.wb .hotword-fields > small { color: var(--dim); font-size: 9px; line-height: 1.5; }
.wb .profile-list { flex: 1; min-height: 60px; overflow-y: auto; border: 1px solid var(--line); border-top: 0;
  border-radius: 0 0 10px 10px; }
.wb .profile-row { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 9px; align-items: center;
  min-height: 56px; padding: 10px 11px; border-bottom: 1px solid var(--line); position: relative; }
.wb .profile-row::before { content: ''; position: absolute; inset: 10px auto 10px 0; width: 3px; border-radius: 3px;
  background: var(--profile-color, var(--line)); }
.wb .profile-row:last-child { border-bottom: 0; }
.wb .profile-enabled { width: 15px; height: 15px; padding: 0; accent-color: var(--acc); cursor: pointer; }
.wb .profile-enabled:disabled { cursor: not-allowed; }
.wb .profile-main { min-width: 0; }
.wb .profile-main strong { display: block; font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb .profile-main small { display: block; color: var(--dim); font-size: 9px; margin-top: 4px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.wb .profile-list.selection-disabled .profile-enabled { opacity: .35; }
.wb .info-stage { padding: 14px 16px; flex: 0 0 auto; }
.wb .info-stage .stage-head { margin-bottom: 6px; }
.wb .info-stage h2 { font-size: 15px; }
.wb .spec { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 8px 0;
  border-bottom: 1px solid var(--line); font-size: 11px; }
.wb .spec:last-child { border-bottom: 0; }
.wb .spec span { color: var(--dim); flex: 0 0 auto; }
.wb .spec code { color: var(--text); font-family: ui-monospace, monospace; font-size: 10px; text-align: right; overflow-wrap: anywhere; }

/* ---- 错误横幅（原页同款布局，配色对齐模块一 err 红） ---- */
.wb .alert-banner { position: absolute; top: 64px; right: 22px; z-index: 30; width: min(500px, calc(100% - 44px));
  display: grid; grid-template-columns: 42px 1fr 30px; gap: 13px; align-items: start; padding: 16px; border-radius: 12px;
  background: linear-gradient(0deg, rgba(201, 49, 49, .04), rgba(201, 49, 49, .04)), #fff;
  border: 1px solid rgba(201, 49, 49, .4); box-shadow: 0 8px 30px rgba(0, 0, 0, .08); }
.wb .alert-icon { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 50%;
  background: var(--err); color: #fff; font: 800 24px/1 Georgia, serif; }
.wb .alert-content { min-width: 0; }
.wb .alert-label { display: block; color: var(--err); font: 700 9px/1 ui-monospace, monospace; letter-spacing: .18em; margin-bottom: 5px; }
.wb .alert-content strong { display: block; color: var(--text); font-size: 15px; line-height: 1.4; }
.wb .alert-content p { margin: 6px 0 0; color: #993d3d; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.wb .alert-content small { display: block; margin-top: 7px; color: var(--dim); font-size: 10px; line-height: 1.5; }
.wb .alert-close { width: 30px; height: 30px; border: 0; border-radius: 8px; background: rgba(201, 49, 49, .06);
  color: var(--err); font-size: 20px; cursor: pointer; }
.wb .alert-close:hover { background: rgba(201, 49, 49, .14); }

@media (max-width: 1120px) {
  .wb .stage-grid { grid-template-columns: 1fr; }
  .wb .live-column { position: static; height: 560px; max-height: none; }
}
</style>