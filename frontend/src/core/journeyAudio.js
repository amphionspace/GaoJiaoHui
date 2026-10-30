import { Mic, SR, FRAME, b64frame, wavEncode } from './audio.js'
import { WS_HOST, api } from './api.js'
import { createSpeechDetector } from './journeySpeech.js'
import { store } from './store.js'

/* The managed ASR credential is minted on the server (about one second) and is
   valid for 60 s. Prefetch it while the introduction is still on screen so the
   click that starts listening does not pay for it; 40 s keeps 20 s of headroom
   for the WebSocket handshake. */
const SESSION_REUSE_MS = 40000
let preparedSession = null
let sessionPending = null

function takePreparedSession() {
  if (!preparedSession) return ''
  const { url, at } = preparedSession
  preparedSession = null
  return Date.now() - at < SESSION_REUSE_MS ? url : ''
}

function rememberSession(session) {
  const url = session && typeof session.url === 'string' ? session.url : ''
  preparedSession = url ? { url, at: Date.now() } : null
  return session
}

export function prefetchAsrSession() {
  if (!store.asrManaged) return Promise.resolve('')
  if (preparedSession && Date.now() - preparedSession.at < SESSION_REUSE_MS) return Promise.resolve(preparedSession.url)
  if (sessionPending) return sessionPending
  sessionPending = (async () => {
    try {
      const session = rememberSession(await api('/asr-session', { prefix: '/api/journey', method: 'POST' }))
      return session?.url || ''
    } catch {
      return ''
    } finally {
      sessionPending = null
    }
  })()
  return sessionPending
}

export class JourneyRecorder {
  constructor(key, handlers = {}, { context = null } = {}) {
    this.key = key
    this.managed = store.asrManaged === true
    this.handlers = handlers
    this.text = ''
    this.closed = false
    this.frames = 0
    this.samples = []
    this.sampleSeconds = 0
    this.voicedSeconds = 0
    this.silentSeconds = 0
    this.segments = new Map()
    this.segmentSequence = 0
    this.processing = Promise.resolve()
    this.queuedChunks = 0
    this.idleSeconds = 0
    this.detectedSpeechSeconds = 0
    this.context = context
    this.pendingPcm = new Int16Array(8000)
    this.pendingSamples = 0
  }

  acceptSegment(message) {
    // An ASR model may emit plausible text for silence. Never accept it until
    // the local detector has actually observed speech in this recording.
    if (this.closed || this.detectedSpeechSeconds < .16) return
    const final = message.type === 'transcription.final'
    const key = message.segment_id != null ? `segment:${message.segment_id}` : `turn:${this.segmentSequence}`
    const previous = this.segments.get(key)
    if (previous?.final && !final) return
    const text = message.text ?? message.transcript ?? ''
    this.segments.set(key, { text, final })
    if (final && message.segment_id == null) this.segmentSequence++
    this.text = [...this.segments.values()].map(segment => segment.text).filter(Boolean).join('\n')
    this.handlers.onText?.(this.text, final)
  }

  fail(message) {
    this.failure = new Error(message)
    const finishing = Boolean(this.resolveFinal)
    this.stop()
    if (!finishing) this.handlers.onError?.(message)
  }

  async start() {
    try { await this.startInput() }
    catch (error) { this.stop(); throw error }
    finally { clearTimeout(this.startupTimer) }
  }

  async waitForStart(pending, message, milliseconds = 20000) {
    let timer
    try {
      return await Promise.race([pending, new Promise((_, reject) => {
        this.rejectStart = () => reject(this.failure || new Error('会话已结束'))
        timer = setTimeout(() => reject(new Error(message)), milliseconds)
      })])
    } finally { clearTimeout(timer); this.rejectStart = null }
  }

  async takeSession(signal) {
    const prepared = takePreparedSession()
    if (prepared) return { url: prepared }
    if (sessionPending) await sessionPending
    const ready = takePreparedSession()
    if (ready) return { url: ready }
    return rememberSession(await api('/asr-session', {
      prefix: '/api/journey', method: 'POST', signal,
    }))
  }

  async startInput() {
    this.handlers.onPhase?.('microphone')
    this.mic = new Mic({ context: this.context })
    // Obtain permission before opening an upstream session that expects incoming audio.
    await this.waitForStart(this.mic.prepare({ echoCancellation: true, noiseSuppression: true, autoGainControl: false }), '还没有接通麦克风，请在浏览器中允许麦克风权限，再点击继续录音。')
    if (this.closed) return
    this.startupTimer = setTimeout(() => this.fail('语音准备超过 20 秒，请检查网络后重试，或改用文字记录。'), 20000)
    this.handlers.onPhase?.('speech')
    const pending = createSpeechDetector().then(async detector => {
      if (this.closed) { await detector.dispose(); return null }
      return detector
    })
    // Mint the temporary ASR credential while the local detector finishes; it
    // used to be requested only afterwards, adding its full latency to every start.
    if (this.managed) this.sessionController = new AbortController()
    const sessionPending = this.managed ? this.takeSession(this.sessionController.signal) : null
    sessionPending?.catch(() => {})
    this.detector = await this.waitForStart(pending, '人声检测未能启动，请刷新页面重试，或改用文字记录。')
    if (this.closed) { await this.detector?.dispose(); this.detector = null; return }
    this.handlers.onPhase?.('connection')
    let socketUrl = `${WS_HOST}/asr/v1/target-dialogue?api_key=${encodeURIComponent(this.key)}`
    if (this.managed) {
      const session = await this.waitForStart(sessionPending, '语音授权超时，请重试或改用文字记录。')
      if (this.closed) return
      let parsed
      try { parsed = new URL(session.url) } catch { throw new Error('语音连接地址无效，请检查服务配置。') }
      if (parsed.protocol !== 'wss:' || parsed.username || parsed.password || parsed.hash) throw new Error('语音连接地址无效，请检查服务配置。')
      socketUrl = session.url
    }
    const socket = this.socket = new WebSocket(socketUrl)
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => fail('语音连接超时，请重试。'), 12000)
      const fail = message => { clearTimeout(timeout); reject(new Error(message)) }
      this.rejectStart = () => fail('会话已结束')
      socket.onopen = () => { clearTimeout(timeout); resolve() }
      socket.onerror = () => fail('语音服务连接失败，请检查网络或设置。')
      socket.onclose = () => fail('语音连接已关闭，请检查设置后重试。')
    }).catch(error => { this.stop(); throw error })
    this.rejectStart = null
    if (this.closed) return
    let ready
    const sessionReady = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('语音识别服务准备超时，请重试或改用文字记录。')), 15000)
      ready = () => { clearTimeout(timeout); this.rejectStart = null; resolve() }
      this.rejectStart = () => { clearTimeout(timeout); reject(this.failure || new Error('会话已结束')) }
    })
    socket.onmessage = event => {
      let message
      try { message = JSON.parse(event.data) } catch { return }
      const type = message.type || ''
      if (this.managed) {
        if (type === 'Begin') ready()
        else if (type === 'Turn' && message.turn_order != null) this.acceptSegment({
          type: message.end_of_turn ? 'transcription.final' : 'transcription.partial',
          segment_id: message.turn_order, text: message.transcript || '',
        })
        else if (type === 'Termination') {
          if (this.resolveFinal) this.resolveFinal(this.text)
          else this.fail('语音会话已结束，已记录的内容会保留，可以继续录音。')
        } else if (type === 'Error') this.fail('语音识别服务暂时不可用。已显示的讲述会保留，可以重试或改用文字记录。')
      } else if (type === 'session.created') ready()
      else if (type === 'transcription.partial' || type === 'transcription.final') this.acceptSegment(message)
      else if (type === 'session.done') this.resolveFinal?.(this.text)
      else if (type === 'error') this.fail('语音识别服务暂时不可用。已显示的讲述会保留，可以重试或改用文字记录。')
    }
    socket.onerror = () => { if (!this.closed) this.fail('语音连接中断，已记录的内容会保留。') }
    socket.onclose = () => {
      if (this.resolveFinal) {
        this.handlers.onWarning?.('识别连接在收尾时断开，请核对最后一句。')
        this.resolveFinal(this.text)
      }
      else if (!this.closed) this.fail('语音连接已断开，可以继续录音或输入文字。')
    }
    if (!this.managed) socket.send(JSON.stringify({ type: 'session.update', session: {
      participants: [], filter: { mode: 'open' },
      audio: { format: 'pcm_s16le', sample_rate_hz: SR, channels: 1 },
      recognition: { mode: 'role_separation', response_speed: 'balanced' },
    } }))
    try { await sessionReady } catch (error) { this.stop(); throw error }
    if (this.closed) return
    try {
      await this.mic.start(pcm => {
        if (this.closed || socket.readyState !== WebSocket.OPEN) return
        if (++this.queuedChunks > 24) { this.fail('音频处理跟不上录音，请关闭其他占用较高的程序后重试。'); return }
        this.processing = this.processing.then(async () => {
          if (!this.closed) await this.detector.process(pcm, this.acceptAudio)
        }).catch(() => { if (!this.closed) this.fail('人声检测中断，讲述已保留，请重试录音。') })
          .finally(() => { this.queuedChunks-- })
      }, null, { echoCancellation: true, noiseSuppression: true, autoGainControl: false })
    } catch (error) { this.stop(); throw error }
    if (!this.closed) this.handlers.onPhase?.('ready')
    if (!this.closed) this.micWatchdog = setTimeout(() => {
      if (!this.closed && !this.frames) {
        this.handlers.onError?.('没有收到麦克风音频，请检查输入设备和麦克风权限。')
        this.stop()
      }
    }, 6000)
  }

  acceptAudio = (pcm, speaking, voiced) => {
    if (this.closed || this.socket?.readyState !== WebSocket.OPEN) return
    let total = 0
    for (const sample of pcm) total += sample * sample
    const rms = Math.sqrt(total / pcm.length) / 32768
    const seconds = pcm.length / SR
    if (voiced) {
      this.detectedSpeechSeconds += seconds
      if (this.detectedSpeechSeconds >= .16) this.handlers.onAudio?.()
    }
    this.handlers.onLevel?.(Math.min(1, rms * 10), speaking)
    if (speaking) { this.heardSpeech = true; this.idleSeconds = 0 }
    else this.idleSeconds += seconds
    this.handlers.onActivity?.(this.idleSeconds, Boolean(this.heardSpeech))
    if (!this.sampleSent && this.handlers.onSample) {
      if (voiced) { this.voicedSeconds += seconds; this.silentSeconds = 0 }
      else this.silentSeconds += seconds
      if (this.silentSeconds > 2 && this.voicedSeconds < 1) {
        this.samples = []; this.sampleSeconds = 0; this.voicedSeconds = 0
      }
      if (this.voicedSeconds > 0 && this.silentSeconds <= .8) { this.samples.push(pcm.slice()); this.sampleSeconds += seconds }
      if (this.sampleSeconds >= 10 && this.voicedSeconds >= 5) this.emitSample()
      if (this.sampleSeconds >= 14 && !this.sampleSent) {
        this.samples = []; this.sampleSeconds = 0; this.voicedSeconds = 0
      }
    }
    if (this.managed) {
      // FourHz accepts binary PCM. Accumulate at most 500 ms per message.
      for (let offset = 0; offset < pcm.length;) {
        const length = Math.min(this.pendingPcm.length - this.pendingSamples, pcm.length - offset)
        this.pendingPcm.set(pcm.subarray(offset, offset + length), this.pendingSamples)
        this.pendingSamples += length; offset += length
        if (this.pendingSamples === this.pendingPcm.length) this.flushManagedAudio()
      }
    } else for (let i = 0; i < pcm.length; i += FRAME) {
      this.socket.send(JSON.stringify({ type: 'input_audio_buffer.append', audio: b64frame(pcm.subarray(i, i + FRAME)) }))
      this.frames++
    }
  }

  flushManagedAudio() {
    if (!this.pendingSamples || this.closed || this.socket?.readyState !== WebSocket.OPEN) return
    const bytes = new Uint8Array(this.pendingSamples * 2)
    const view = new DataView(bytes.buffer)
    for (let index = 0; index < this.pendingSamples; index++) view.setInt16(index * 2, this.pendingPcm[index], true)
    this.socket.send(bytes)
    this.frames++
    this.pendingSamples = 0
  }

  emitSample() {
    if (this.sampleSent || this.voicedSeconds < 5 || this.sampleSeconds > 15) return
    this.sampleSent = true
    this.handlers.onSample?.(wavEncode(this.samples))
    this.samples = []
  }

  finish() {
    if (this.finishPromise) return this.finishPromise
    this.mic?.stop()
    clearTimeout(this.micWatchdog)
    clearTimeout(this.startupTimer)
    this.handlers.onLevel?.(0, false)
    this.processing = this.processing.then(async () => {
      if (!this.closed) await this.detector.flush(this.acceptAudio)
      if (this.managed) this.flushManagedAudio()
      this.emitSample()
      if (this.failure) throw this.failure
    })
    this.finishPromise = this.processing.then(() => new Promise(resolve => {
      const done = text => { clearTimeout(this.finalTimer); this.resolveFinal = null; resolve(text) }
      this.resolveFinal = done
      this.finalTimer = setTimeout(() => {
        this.handlers.onWarning?.('识别收尾超时，已保留收到的内容，请核对最后一句。')
        done(this.text)
      }, this.managed ? 65000 : 10000)
      if (this.socket?.readyState === WebSocket.OPEN && this.frames) {
        this.socket.send(JSON.stringify(this.managed ? { type: 'Terminate' } : { type: 'input_audio_buffer.commit', final: true }))
      } else done(this.text)
    })).then(text => {
      this.stop()
      if (this.failure) throw this.failure
      return text
    }).catch(error => { this.stop(); throw error })
    return this.finishPromise
  }

  stop() {
    this.closed = true
    this.sessionController?.abort()
    this.rejectStart?.()
    this.rejectStart = null
    this.mic?.stop()
    if (this.detector && !this.detectorDisposal) {
      this.detectorDisposal = this.processing.catch(() => {}).then(() => this.detector.dispose()).catch(() => {})
    }
    this.resolveFinal?.(this.text)
    clearTimeout(this.finalTimer)
    clearTimeout(this.micWatchdog)
    clearTimeout(this.startupTimer)
    if (this.socket) {
      this.socket.onopen = this.socket.onmessage = this.socket.onerror = this.socket.onclose = null
      this.socket.close()
    }
    this.samples = []
    this.pendingSamples = 0
  }
}

export class JourneySound {
  constructor() {
    this.music = new Audio('/journey/welcome-music.wav')
    this.music.loop = true
    this.music.volume = .16
    this.generation = 0
  }
  unlock() {
    try {
      // Keep the actual output context alive across ASR and asynchronous TTS.
      const Context = window.AudioContext || window.webkitAudioContext
      this.context ||= new Context()
      if (this.context.state === 'running') return Promise.resolve(true)
      return this.context.resume().then(() => this.context.state === 'running', () => false)
    } catch {
      return Promise.resolve(false)
    }
  }
  async readyOutput() {
    let timer
    try {
      return await Promise.race([
        this.unlock(),
        new Promise(resolve => { timer = setTimeout(() => resolve(false), 1500) }),
      ])
    } finally { clearTimeout(timer) }
  }
  async play(url) {
    this.stop()
    const generation = this.generation
    const ready = await this.readyOutput()
    if (generation !== this.generation) return false
    if (!ready) throw new DOMException('请点击播放以开启声音。', 'NotAllowedError')
    const response = await fetch(url, { signal: AbortSignal.timeout(15000) })
    if (!response.ok) throw new Error('音频读取失败，请重试。')
    const buffer = await this.context.decodeAudioData(await response.arrayBuffer())
    if (generation !== this.generation) return false
    this.buffer = buffer; this.offset = 0; this.paused = false
    return new Promise((resolve, reject) => {
      this.finish = (ended = false) => { this.finish = null; this.clearSource(); resolve(ended) }
      try { this.startSource() } catch (error) { this.finish = null; this.clearSource(); reject(error) }
    })
  }
  startSource() {
    const source = this.source = this.context.createBufferSource()
    source.buffer = this.buffer
    source.connect(this.context.destination)
    source.onended = () => { if (this.source === source) this.finish?.(true) }
    this.startedAt = this.context.currentTime
    source.start(0, this.offset)
  }
  clearSource() {
    if (!this.source) return
    this.source.onended = null
    try { this.source.stop() } catch { /* The buffer may have already ended. */ }
    this.source.disconnect(); this.source = null
  }
  greet(text) {
    this.stop()
    if (!window.speechSynthesis) return Promise.reject(new Error('当前浏览器不支持欢迎语播报。'))
    const generation = this.generation
    return new Promise((resolve, reject) => {
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'zh-CN'; utterance.rate = .95
      utterance.voice = window.speechSynthesis.getVoices().find(voice => /^zh[-_]CN/i.test(voice.lang)) || null
      const finish = value => { clearTimeout(timeout); if (generation === this.generation) { this.music.pause(); this.finish = null }; resolve(value) }
      const timeout = setTimeout(() => {
        if (generation !== this.generation) { resolve(false); return }
        window.speechSynthesis.cancel(); this.music.pause(); this.finish = null
        reject(new Error('请点击开始体验，开启语音播报。'))
      }, 20000)
      this.finish = () => finish(false)
      utterance.onstart = () => { if (generation === this.generation) this.music.play().catch(() => {}) }
      utterance.onend = () => finish(true)
      utterance.onerror = event => {
        clearTimeout(timeout)
        if (generation !== this.generation) { resolve(false); return }
        this.music.pause(); this.finish = null
        reject(Object.assign(new Error('欢迎语暂时无法播放。'), { name: event.error === 'not-allowed' ? 'NotAllowedError' : 'AudioError' }))
      }
      window.speechSynthesis.speak(utterance)
    })
  }
  pause() {
    if (this.source) { this.offset += this.context.currentTime - this.startedAt; this.clearSource(); this.paused = true }
    this.music.pause()
  }
  async resume() {
    if (!this.paused || !this.buffer || !this.finish) return
    const generation = this.generation
    const ready = await this.readyOutput()
    if (generation !== this.generation) return
    if (!ready) throw new DOMException('请点击播放以开启声音。', 'NotAllowedError')
    if (this.offset >= this.buffer.duration) this.finish(true)
    else { this.startSource(); this.paused = false }
  }
  stop() {
    this.finish?.(); this.generation++; this.clearSource(); this.buffer = null; this.paused = false
    this.music.pause(); window.speechSynthesis?.cancel()
  }
  dispose() { this.stop(); this.context?.close().catch(() => {}); this.music.removeAttribute('src'); this.music.load() }
}

const JOURNEY_VOICE = /^journey_[a-f0-9]{32}$/
const activeVoices = new Set()
const cleanupTasks = new Map()
const voiceLock = name => `journey-voice:${name}`

function pendingVoices() {
  try {
    const pending = JSON.parse(localStorage.getItem('journey_cleanup') || '[]')
    return Array.isArray(pending) ? pending.filter(name => typeof name === 'string' && JOURNEY_VOICE.test(name)) : []
  } catch { return [] }
}
function rememberVoice(name) {
  try { localStorage.setItem('journey_cleanup', JSON.stringify([...new Set([...pendingVoices(), name])])) } catch { /* Storage may be disabled. */ }
}
function forgetVoice(name) {
  try { localStorage.setItem('journey_cleanup', JSON.stringify(pendingVoices().filter(item => item !== name))) } catch { /* Retry at the next quota recovery. */ }
}
async function deleteJourneyVoice(key, name) {
  try {
    await api('/tts/v1/audio/voices/' + encodeURIComponent(name), {
      prefix: '/api/journey', method: 'DELETE', headers: { 'X-API-Key': key }, signal: AbortSignal.timeout(15000), keepalive: true,
    })
  } catch (error) {
    if (error.status !== 404) { rememberVoice(name); return false }
  }
  forgetVoice(name)
  return true
}
async function holdVoice(name) {
  if (!globalThis.navigator?.locks) return () => {}
  let release, acquired, failed
  const held = new Promise(resolve => { release = resolve })
  const ready = new Promise((resolve, reject) => { acquired = resolve; failed = reject })
  navigator.locks.request(voiceLock(name), () => { acquired(); return held }).catch(failed)
  await ready
  return release
}
const quotaError = error => /voice limit|voice.{0,15}quota|音色.{0,10}(?:上限|配额)/i.test(error.message || '')

export function voiceFailureMessage(error) {
  const message = error?.message || ''
  const step = error?.stage === 'synthesis' ? '声音合成失败' : '本人音色未能创建'
  if (/Voice management requires healthy backends/i.test(message)) {
    const backend = message.match(/backends for:\s*([\w., -]+)/i)?.[1]?.trim() || 'TTS'
    return `本人音色未能创建：网关报告 ${backend} 未通过音色注册的健康检查。需要工作人员恢复注册服务；重复录音无法解决。`
  }
  if (/Selected voice model backend .* is unavailable/i.test(message)) return `${step}：本人音色模型服务暂未运行，请工作人员恢复 TTS 服务后重试。`
  if (/CERTIFICATE_VERIFY_FAILED|certificate verify failed/i.test(message)) return `${step}：语音网关的证书连接失败，请工作人员检查代理配置。`
  if ([401, 403].includes(error?.status) && /百炼/.test(message)) return `${step}：${message}。请检查百炼密钥的音色注册及语音合成权限。`
  if ([401, 403].includes(error?.status)) return `${step}：语音网关密钥无效或权限不足，请工作人员检查设置。`
  if (/timeout/i.test(error?.name) || /timed? ?out|超时/i.test(message)) return `${step}：语音服务响应超时，可以重试。`
  return `${step}：${message || '语音服务暂时不可用，请稍后重试。'}`
}

export class JourneyVoice {
  constructor(key, sessionId = '') {
    this.key = key
    this.sessionId = sessionId
    this.name = `journey_${crypto.randomUUID().replaceAll('-', '')}`
    this.disposed = false
    this.abort = new AbortController()
  }
  request(path, options = {}) {
    const headers = { 'X-API-Key': this.key, ...options.headers }
    if (this.sessionId) headers['X-Journey-Session'] = this.sessionId
    return api(path, { ...options, prefix: '/api/journey', headers })
  }
  register(blob) {
    if (this.registration) return this.registration
    if (this.disposed) return Promise.reject(new DOMException('Cancelled', 'AbortError'))
    activeVoices.add(this.name)
    this.registration = this.registerSample(blob).catch(error => { error.stage = 'registration'; throw error })
    return this.registration
  }
  async registerSample(blob) {
    this.releaseLock = await holdVoice(this.name)
    await cleanJourneyVoices(this.key)
    if (this.disposed) throw new DOMException('Cancelled', 'AbortError')
    const data = new FormData()
    data.append('voice_name', this.name)
    data.append('audio_file', blob, `${this.name}.wav`)
    // Persist before uploading: page termination can otherwise strand a server voice.
    rememberVoice(this.name)
    // The dedicated worker transcribes this exact sample and extracts its clone prompt.
    const upload = () => this.request('/tts/v1/audio/voices', { method: 'POST', body: data, signal: AbortSignal.timeout(240000) })
    let result
    try { result = await upload() } catch (error) {
      if (!quotaError(error) || this.disposed) throw error
      const removed = await cleanJourneyVoices(this.key, { recoverOrphans: true })
      if (this.disposed) throw new DOMException('Cancelled', 'AbortError')
      if (!removed) throw new Error('该账号的音色名额已满，没有可回收的旅程音色。请工作人员核对配额，确认后清理旧音色或增加名额，再在当前手记重试。')
      result = await upload()
    }
    if (!['ready', 'success', 'completed'].includes(result?.status)) throw new Error('网关尚未确认音色就绪，请稍后重试。')
    if (result.voice?.voice_name && result.voice.voice_name !== this.name) throw new Error('网关返回的音色与本次录音不一致，请重试。')
    this.backend = result.model || 'journey'
    this.ready = true
    return result
  }
  async synthesize(text) {
    if (!this.registration) throw new Error('清晰录音不足，可以再补充几句话。')
    await this.registration
    if (this.disposed) throw new DOMException('Cancelled', 'AbortError')
    let blob
    try { blob = await this.request('/tts/v1/audio/speech', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.any([this.abort.signal, AbortSignal.timeout(240000)]),
      body: JSON.stringify({ voice: this.name, input: text, response_format: 'wav', sample_rate: 24000 }),
    })
    } catch (error) {
      if (error.status === 404 || error.status === 410) this.ready = false
      error.stage = 'synthesis'; throw error
    }
    if (!(blob instanceof Blob) || !blob.size) throw Object.assign(new Error('没有收到可播放的音频。'), { stage: 'synthesis' })
    return blob
  }
  async remove() {
    if (await deleteJourneyVoice(this.key, this.name)) this.ready = false
  }
  dispose() {
    if (this.disposal) return this.disposal
    this.disposed = true; this.abort.abort()
    this.disposal = (async () => {
      // Never delete before a pending POST settles: it could recreate the voice.
      try { await this.registration } catch { /* Failed uploads may still need cleanup. */ }
      if (this.registration) await this.remove()
      activeVoices.delete(this.name); this.releaseLock?.()
    })()
    return this.disposal
  }
}

export async function cleanJourneyVoices(key, { recoverOrphans = false } = {}) {
  if (!key) return 0
  const previous = cleanupTasks.get(key) || Promise.resolve()
  const task = previous.catch(() => {}).then(async () => {
    const names = new Set(pendingVoices())
    if (recoverOrphans) {
      try {
        const response = await api('/tts/v1/audio/voices', { prefix: '/api/journey', headers: { 'X-API-Key': key }, signal: AbortSignal.timeout(15000) })
        const list = response?.voices || response?.items || (Array.isArray(response) ? response : [])
        for (const item of list) {
          const name = typeof item === 'string' ? item : item.voice_name || item.name
          if (JOURNEY_VOICE.test(name)) names.add(name)
        }
      } catch { /* Known local entries can still be reclaimed. */ }
    }
    let removed = 0
    for (const name of names) {
      if (activeVoices.has(name)) continue
      const remove = async () => { if (!activeVoices.has(name) && await deleteJourneyVoice(key, name)) removed++ }
      if (globalThis.navigator?.locks) {
        await navigator.locks.request(voiceLock(name), { ifAvailable: true }, lock => lock && remove())
      } else await remove()
    }
    return removed
  })
  cleanupTasks.set(key, task)
  try { return await task } finally { if (cleanupTasks.get(key) === task) cleanupTasks.delete(key) }
}
