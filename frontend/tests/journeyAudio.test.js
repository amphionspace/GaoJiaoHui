import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFile } from 'node:fs/promises'
import { webcrypto } from 'node:crypto'

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

async function audioModule(api = async () => ({}), options = {}) {
  class Socket {
    static OPEN = 1
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; Socket.latest = this; queueMicrotask(() => { this.readyState = 1; this.onopen?.() }) }
    send(message) {
      const data = JSON.parse(message)
      this.sent.push(data)
      if (data.type === 'session.update' && !options.waitForReady) queueMicrotask(() => this.receive({ type: 'session.created' }))
    }
    close() { this.readyState = 3 }
    receive(message) { this.onmessage?.({ data: JSON.stringify(message) }) }
  }
  class Mic {
    static latest
    constructor() { Mic.latest = this }
    async start(callback) { this.callback = callback }
    stop() { this.stopped = true }
  }
  class Audio {
    constructor() { this.paused = true }
    play() { this.paused = false; return Promise.resolve() }
    pause() { this.paused = true }
    load() {}
    removeAttribute() {}
  }
  class AudioContext {
    static instances = []
    static allowResume = true
    constructor() {
      this.state = 'suspended'; this.currentTime = 0; this.sources = []; this.started = deferred()
      AudioContext.instances.push(this)
    }
    async resume() {
      if (options.resuming) await options.resuming.promise
      if (AudioContext.allowResume) this.state = 'running'
    }
    async close() { this.state = 'closed' }
    async decodeAudioData() { return options.decoding ? options.decoding.promise : { duration: 12 } }
    createBufferSource() {
      const context = this
      const source = {
        connect() {}, disconnect() {}, stop() { this.stopped = true },
        start(when, offset) { this.offset = offset; this.started = true; context.started.resolve(this) },
      }
      this.sources.push(source)
      return source
    }
  }
  const storage = options.storage || new Map()
  const ctx = vm.createContext({ console, setTimeout, clearTimeout, queueMicrotask, WebSocket: Socket, Blob, FormData, AbortSignal, AbortController, DOMException, crypto: webcrypto, Audio,
    navigator: { locks: options.locks },
    fetch: async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(44) }),
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    window: { AudioContext, speechSynthesis: { cancel() {} } },
  })
  const source = await readFile(new URL('../src/core/journeyAudio.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(source, { context: ctx })
  await module.link(specifier => {
    const values = specifier === './audio.js'
      ? { Mic, SR: 16000, FRAME: 3200, b64frame: () => 'pcm', wavEncode: () => new Blob(['audio']) }
      : specifier === './journeySpeech.js' ? { createSpeechDetector: async () => ({
          process: async (pcm, emit) => emit(pcm, pcm.some(value => value !== 0), pcm.some(value => value !== 0)),
          flush() {}, dispose() {},
        }) }
      : { WS_HOST: 'wss://example.test', api }
    return new vm.SyntheticModule(Object.keys(values), function () { for (const [key, value] of Object.entries(values)) this.setExport(key, value) }, { context: ctx })
  })
  await module.evaluate()
  return { ...module.namespace, Socket, Mic, AudioContext, storage }
}

test('finishing commits once and waits for the last corrected transcript', async () => {
  const { JourneyRecorder, Socket, Mic } = await audioModule()
  const received = []
  const recorder = new JourneyRecorder('test-only', { onText: text => received.push(text) })
  await recorder.start()
  Mic.latest.callback(new Int16Array(3200).fill(900))
  assert.ok(Socket.latest.url.startsWith('wss://example.test/asr/v1/target-dialogue?'))
  assert.equal(Socket.latest.sent[0].session.filter.mode, 'open')
  Socket.latest.receive({ type: 'transcription.partial', segment_id: 1, text: '今天看到一个机' })
  const first = recorder.finish(), second = recorder.finish()
  await new Promise(resolve => setImmediate(resolve))
  Socket.latest.receive({ type: 'transcription.final', segment_id: 1, text: '今天看到一个机器人。' })
  Socket.latest.receive({ type: 'session.done' })
  assert.equal(await first, '今天看到一个机器人。')
  assert.equal(await second, '今天看到一个机器人。')
  assert.equal(received.at(-1), '今天看到一个机器人。')
  assert.equal(Socket.latest.sent.filter(event => event.type === 'input_audio_buffer.commit').length, 1)
  assert.ok(Mic.latest.stopped)
  assert.equal(Socket.latest.readyState, 3)
})

test('segmented transcripts preserve earlier speech and await session completion', async () => {
  const { JourneyRecorder, Socket, Mic } = await audioModule()
  const received = []
  const recorder = new JourneyRecorder('test-only', { onText: (text, final) => received.push({ text, final }) })
  await recorder.start()
  Mic.latest.callback(new Int16Array(3200).fill(900))
  Socket.latest.receive({ type: 'transcription.partial', segment_id: 0, text: '今天想留下' })
  Socket.latest.receive({ type: 'transcription.final', segment_id: 0, text: '今天想留下一个想法。' })
  Socket.latest.receive({ type: 'transcription.final', segment_id: 0, text: '今天想留下一个想法。' })
  Socket.latest.receive({ type: 'transcription.partial', segment_id: 0, text: '过期的草稿' })
  Socket.latest.receive({ type: 'transcription.partial', segment_id: 1, text: '给爸妈做' })
  assert.equal(recorder.text, '今天想留下一个想法。\n给爸妈做')
  let finished = false
  const pending = recorder.finish().then(text => { finished = true; return text })
  await new Promise(resolve => setImmediate(resolve))
  Socket.latest.receive({ type: 'transcription.final', segment_id: 1, text: '给爸妈做吃药提醒。' })
  await Promise.resolve()
  assert.equal(finished, false)
  Socket.latest.receive({ type: 'session.done' })
  assert.equal(await pending, '今天想留下一个想法。\n给爸妈做吃药提醒。')
  assert.equal(received.at(-1).text, '今天想留下一个想法。\n给爸妈做吃药提醒。')
})

test('capture waits for ASR session readiness and leaving cancels initialization', async () => {
  const { JourneyRecorder, Socket, Mic } = await audioModule(undefined, { waitForReady: true })
  const recorder = new JourneyRecorder('test-only')
  const starting = recorder.start()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(Mic.latest, undefined)
  Socket.latest.receive({ type: 'session.created' })
  await starting
  assert.ok(Mic.latest)
  recorder.stop()
  const second = new JourneyRecorder('test-only')
  const cancelled = second.start()
  await new Promise(resolve => setImmediate(resolve))
  second.stop()
  await assert.rejects(cancelled, /会话已结束/)
})

test('ASR errors during finalization keep the transcript and fail explicitly', async () => {
  const { JourneyRecorder, Socket, Mic } = await audioModule()
  const recorder = new JourneyRecorder('test-only')
  await recorder.start()
  Mic.latest.callback(new Int16Array(3200).fill(900))
  Socket.latest.receive({ type: 'transcription.partial', segment_id: 1, text: '已经识别的内容' })
  const finishing = recorder.finish()
  Socket.latest.receive({ type: 'error', message: 'backend unavailable' })
  await assert.rejects(finishing, /语音识别服务暂时不可用/)
  assert.equal(recorder.text, '已经识别的内容')
  assert.ok(Mic.latest.stopped)
})

test('disposed sessions delete a voice even when registration resolves late', async () => {
  const registration = deferred(), uploading = deferred(), calls = []
  const { JourneyVoice } = await audioModule(async (path, options) => {
    calls.push({ path, method: options.method })
    if (options.method === 'POST') { uploading.resolve(); return registration.promise }
    return null
  })
  const voice = new JourneyVoice('test-only')
  const pending = voice.register(new Blob(['sample']))
  await uploading.promise
  const disposing = voice.dispose()
  assert.equal(calls.filter(call => call.method === 'DELETE').length, 0)
  registration.resolve({ status: 'ready' })
  await pending
  await disposing
  assert.equal(calls.filter(call => call.method === 'DELETE').length, 1)
  assert.ok(calls.filter(call => call.method === 'DELETE').every(call => call.path.endsWith(voice.name)))
  await assert.rejects(voice.synthesize('不应生成'), { name: 'AbortError' })
})

test('voice registration failure never triggers speech synthesis', async () => {
  const calls = []
  const { JourneyVoice } = await audioModule(async (path) => { calls.push(path); throw new Error('quota') })
  const voice = new JourneyVoice('test-only')
  await assert.rejects(voice.register(new Blob(['sample'])), /quota/)
  await assert.rejects(voice.synthesize('test'), /quota/)
  assert.equal(calls.length, 1)
})

test('journey registration and synthesis use the dedicated service and the same recorded voice', async () => {
  const calls = []
  const { JourneyVoice } = await audioModule(async (path, options = {}) => {
    calls.push({ path, prefix: options.prefix, method: options.method, body: options.body })
    if (path === '/tts/v1/audio/voices') return { status: 'ready' }
    if (path === '/tts/v1/audio/speech') return new Blob(['wav'])
    throw new Error('unexpected path')
  })
  const voice = new JourneyVoice('test-only')
  await voice.register(new Blob(['sample']))
  const blob = await voice.synthesize('未来的我，请继续保持好奇。')
  const registration = calls.find(call => call.path === '/tts/v1/audio/voices')
  assert.equal(registration.body.has('model'), false)
  assert.ok(calls.every(call => call.prefix === '/api/journey'))
  assert.equal(registration.body.get('voice_name'), voice.name)
  assert.equal(await registration.body.get('audio_file').text(), 'sample')
  assert.equal(registration.body.has('ref_text'), false)
  const speech = calls.find(call => call.path === '/tts/v1/audio/speech')
  assert.ok(blob.size)
  assert.equal(speech.method, 'POST')
  assert.deepEqual(JSON.parse(speech.body), {
    voice: voice.name,
    input: '未来的我，请继续保持好奇。',
    response_format: 'wav',
    sample_rate: 24000,
  })
})

test('an unhealthy registration backend prevents synthesis and reports the exact failed stage', async () => {
  const calls = []
  const { JourneyVoice, voiceFailureMessage } = await audioModule(async (path, options = {}) => {
    calls.push({ path, method: options.method, body: options.body })
    throw Object.assign(new Error('Voice management requires healthy backends for: qwen3-1.7b-tts'), { status: 503 })
  })
  const voice = new JourneyVoice('test-only')
  await assert.rejects(voice.register(new Blob(['sample'])), error => {
    assert.equal(error.stage, 'registration')
    assert.match(voiceFailureMessage(error), /qwen3-1.7b-tts 未通过音色注册的健康检查/)
    assert.doesNotMatch(voiceFailureMessage(error), /录音不足/)
    return true
  })
  await assert.rejects(voice.synthesize('我是未来的你。'), /healthy backends/)
  assert.equal(calls.length, 1)
})

test('an unavailable selected clone backend is reported without blaming the recording', async () => {
  const { voiceFailureMessage } = await audioModule()
  assert.match(voiceFailureMessage(new Error("Selected voice model backend 'upstream' is unavailable.")), /模型服务暂未运行/)
})

test('missing registered voices and invalid audio do not silently switch synthesis backends', async () => {
  for (const message of ['voice not found', 'invalid audio', 'quota exceeded']) {
    let speechCalls = 0
    const { JourneyVoice } = await audioModule(async path => {
      if (path.endsWith('/voices')) return { status: 'ready' }
      speechCalls++
      throw Object.assign(new Error(message), { status: 400 })
    })
    const voice = new JourneyVoice('test-only')
    await voice.register(new Blob(['sample']))
    await assert.rejects(voice.synthesize('test'), { message })
    assert.equal(speechCalls, 1)
  }
})

test('a successful HTTP upload without a ready status is not treated as a cloned voice', async () => {
  let speechCalls = 0
  const { JourneyVoice } = await audioModule(async path => {
    if (path.endsWith('/speech')) speechCalls++
    return {}
  })
  const voice = new JourneyVoice('test-only')
  await assert.rejects(voice.register(new Blob(['sample'])), /尚未确认音色就绪/)
  await assert.rejects(voice.synthesize('不应播放'), /尚未确认音色就绪/)
  assert.equal(speechCalls, 0)
})

test('playback waits for asynchronous AudioContext activation after a click', async () => {
  const resuming = deferred()
  const { JourneySound, AudioContext } = await audioModule(undefined, { resuming })
  const sound = new JourneySound(), playing = sound.play('blob:sample')
  const context = AudioContext.instances[0]
  assert.equal(context.sources.length, 0)
  resuming.resolve()
  const source = await context.started.promise
  source.onended()
  assert.equal(await playing, true)
})

test('cancelled playback settles and stops the sound player', async () => {
  const { JourneySound, AudioContext } = await audioModule()
  const sound = new JourneySound()
  await sound.unlock()
  const playing = sound.play('blob:sample')
  const source = await AudioContext.instances[0].started.promise
  sound.stop()
  assert.equal(await playing, false)
  assert.ok(source.stopped)
  assert.ok(sound.music.paused)
})

test('the output unlocked at entry plays after asynchronous synthesis without another click', async () => {
  const synthesis = deferred()
  const { JourneySound, JourneyVoice, AudioContext } = await audioModule(async path => {
    if (path.endsWith('/voices')) return { status: 'ready' }
    return synthesis.promise
  })
  const sound = new JourneySound(), voice = new JourneyVoice('test-only')
  await sound.unlock()
  await voice.register(new Blob(['sample']))
  const generating = voice.synthesize('未来的我，照顾好自己。')
  synthesis.resolve(new Blob(['wav']))
  await generating
  const playing = sound.play('blob:generated')
  const source = await AudioContext.instances[0].started.promise
  assert.equal(AudioContext.instances.length, 1)
  assert.ok(source.started)
  source.onended()
  assert.equal(await playing, true)
})

test('pause and resume keep the position and cancellation ignores late audio decoding', async () => {
  const { JourneySound, AudioContext } = await audioModule()
  const sound = new JourneySound()
  await sound.unlock()
  const context = AudioContext.instances[0], playing = sound.play('blob:sample')
  await context.started.promise
  context.currentTime = 3
  sound.pause()
  assert.ok(context.sources[0].stopped)
  context.currentTime = 8
  await sound.resume()
  assert.equal(context.sources[1].offset, 3)
  context.sources[1].onended()
  assert.equal(await playing, true)

  const decoding = deferred(), delayed = await audioModule(undefined, { decoding })
  const cancelled = new delayed.JourneySound()
  await cancelled.unlock()
  const pending = cancelled.play('blob:late')
  cancelled.stop()
  decoding.resolve({ duration: 10 })
  assert.equal(await pending, false)
  assert.equal(delayed.AudioContext.instances[0].sources.length, 0)
})

test('a browser denying output activation produces an explicit playback error', async () => {
  const { JourneySound, AudioContext } = await audioModule()
  AudioContext.allowResume = false
  const sound = new JourneySound()
  await assert.rejects(sound.play('blob:sample'), { name: 'NotAllowedError' })
  assert.equal(AudioContext.instances[0].sources.length, 0)
})

test('quota recovery only removes inactive journey voices and retries registration automatically', async () => {
  const orphan = `journey_${'a'.repeat(32)}`, calls = []
  let uploads = 0
  const { JourneyVoice, storage } = await audioModule(async (path, options = {}) => {
    calls.push({ path, method: options.method })
    if (options.method === 'POST') {
      assert.ok(JSON.parse(storage.get('journey_cleanup')).includes(options.body.get('voice_name')))
      if (++uploads === 1) throw new Error('Voice limit reached (10). Delete an existing voice first.')
      return { status: 'ready' }
    }
    if (options.method === 'DELETE') return null
    return { voices: [orphan, { voice_name: 'gjh_speaker1' }, { name: 'my_saved_voice' }, 'journey_manual', voice.name] }
  })
  const voice = new JourneyVoice('test-only')
  await voice.register(new Blob(['sample']))
  assert.equal(uploads, 2)
  assert.deepEqual(calls.filter(call => call.method === 'DELETE').map(call => call.path), [`/tts/v1/audio/voices/${orphan}`])
  assert.deepEqual(JSON.parse(storage.get('journey_cleanup')), [voice.name])
  await voice.dispose()
  assert.deepEqual(JSON.parse(storage.get('journey_cleanup')), [])
})

test('a full account containing saved voices fails clearly without deleting or synthesizing them', async () => {
  const calls = []
  const { JourneyVoice } = await audioModule(async (path, options = {}) => {
    calls.push({ path, method: options.method })
    if (options.method === 'POST') throw new Error('Voice limit reached (10). Delete an existing voice first.')
    return { voices: ['gjh_speaker1', 'saved_voice'] }
  })
  const voice = new JourneyVoice('test-only')
  await assert.rejects(voice.register(new Blob(['sample'])), /音色名额已满/)
  await assert.rejects(voice.synthesize('不应使用任何默认人声'), /音色名额已满/)
  assert.equal(calls.filter(call => call.method === 'DELETE').length, 0)
  assert.equal(calls.filter(call => call.path.endsWith('/speech')).length, 0)
})

test('pending cleanup finishes before uploading and already deleted voices leave the queue', async () => {
  const stale = `journey_${'b'.repeat(32)}`, deletion = deferred(), deleting = deferred()
  const storage = new Map([['journey_cleanup', JSON.stringify([stale, 'saved_voice'])]])
  let uploaded = false
  const { JourneyVoice } = await audioModule(async (path, options = {}) => {
    if (options.method === 'DELETE') { deleting.resolve(); await deletion.promise; throw Object.assign(new Error('gone'), { status: 404 }) }
    uploaded = true
    assert.ok(!JSON.parse(storage.get('journey_cleanup')).includes(stale))
    return { status: 'ready' }
  }, { storage })
  const voice = new JourneyVoice('test-only'), registering = voice.register(new Blob(['sample']))
  await deleting.promise
  assert.equal(uploaded, false)
  deletion.resolve()
  await registering
  assert.equal(uploaded, true)
})

test('cleanup preserves a journey voice held by another browser tab', async () => {
  const held = new Set(), storage = new Map(), deleted = []
  const locks = {
    async request(name, options, callback) {
      if (typeof options === 'function') { callback = options; options = {} }
      if (held.has(name)) { assert.ok(options.ifAvailable); return callback(null) }
      held.add(name)
      try { return await callback({ name }) } finally { held.delete(name) }
    },
  }
  const api = async (path, options = {}) => {
    if (options.method === 'POST') return { status: 'ready' }
    if (options.method === 'DELETE') { deleted.push(path); return null }
    return { voices: [voice.name] }
  }
  const first = await audioModule(api, { locks, storage }), second = await audioModule(api, { locks, storage })
  const voice = new first.JourneyVoice('test-only')
  await voice.register(new Blob(['sample']))
  await second.cleanJourneyVoices('test-only', { recoverOrphans: true })
  assert.equal(deleted.length, 0)
  await voice.dispose()
  assert.equal(deleted.length, 1)
})

test('voice sampling waits for sufficient speech while preserving natural pauses', async () => {
  const { JourneyRecorder, Mic } = await audioModule()
  const samples = [], recorder = new JourneyRecorder('test-only', { onSample: blob => samples.push(blob) })
  await recorder.start()
  for (let i = 0; i < 10; i++) { Mic.latest.callback(new Int16Array(3200).fill(1500)); await recorder.processing }
  recorder.emitSample()
  assert.equal(samples.length, 0)
  for (let i = 0; i < 6; i++) { Mic.latest.callback(new Int16Array(3200)); await recorder.processing }
  for (let i = 0; i < 40; i++) { Mic.latest.callback(new Int16Array(3200).fill(1500)); await recorder.processing }
  assert.equal(samples.length, 1)
  recorder.emitSample()
  assert.equal(samples.length, 1)
  recorder.stop()
})

test('microphone permission resolving after stop immediately releases the device', async () => {
  const permission = deferred()
  let stopped = false
  const ctx = vm.createContext({ navigator: { mediaDevices: { getUserMedia: () => permission.promise } } })
  const module = new vm.SourceTextModule(await readFile(new URL('../src/core/audio.js', import.meta.url), 'utf8'), { context: ctx })
  await module.link(() => { throw Error('unexpected import') })
  await module.evaluate()
  const mic = new module.namespace.Mic()
  const starting = mic.start(() => assert.fail('cancelled mic must not emit audio'))
  mic.stop()
  permission.resolve({ getTracks: () => [{ stop() { stopped = true } }] })
  await starting
  assert.ok(stopped)
  assert.equal(mic.stream, null)
})
