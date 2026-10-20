import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import * as sessions from '../src/core/session.js'
import * as queues from '../src/core/speechQueue.js'
import * as journey from '../src/core/journey.js'

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const tick = () => new Promise(resolve => setImmediate(resolve))

async function mount(name, options = {}) {
  const document = new EventTarget(), window = new EventTarget()
  globalThis.document = document; globalThis.window = window
  const store = Vue.reactive({ apiKey: 'test-only', logs: [], demoMode: true })
  const storage = new Map()
  const mics = [], sounds = [], voices = [], sockets = [], recorders = []
  class Recorder {
    constructor(key, handlers) { this.handlers = handlers; recorders.push(this) }
    async start() { if (options.recorderStart) await options.recorderStart.promise }
    async finish() { if (options.recorderFinal) this.handlers.onText(options.recorderFinal) }
    stop() { this.stopped = true }
  }
  class Mic {
    constructor() { mics.push(this) }
    async start(callback, collection) {
      this.callback = callback; this.collection = collection
      if (options.permission) await options.permission.promise
    }
    stop() { this.stopped = true }
  }
  class Sound {
    constructor() { this.plays = 0; sounds.push(this) }
    unlock() { return Promise.resolve(true) }
    async greet() { return false }
    async play() { this.plays++; if (options.intro) return options.intro.promise; if (options.introError) throw new Error('audio unavailable'); return true }
    stop() {}
    dispose() {}
  }
  class Voice {
    constructor() { voices.push(this) }
    register(blob) { this.blob = blob; return this.registration = options.voiceAudio ? Promise.resolve() : Promise.reject(new Error('sample rejected')) }
    async synthesize(text) { this.spoken = text; return options.voiceAudio }
    dispose() { this.disposed = true }
  }
  class Socket extends EventTarget {
    constructor() {
      super(); sockets.push(this); this.readyState = 0
      queueMicrotask(() => { if (this.readyState === 0) { this.readyState = 1; this.dispatchEvent(new Event('open')) } })
    }
    send(data) {
      if (typeof data !== 'string') return
      const message = JSON.parse(data)
      if (message.type === 'session.update') queueMicrotask(() => this.receive({ type: 'session.created' }))
      if (message.type === 'input_audio_buffer.commit') queueMicrotask(() => this.receive({ type: 'session.done' }))
    }
    receive(data) { const event = new MessageEvent('message', { data: JSON.stringify(data) }); this.onmessage?.(event); this.dispatchEvent(event) }
    close() { this.readyState = 3; this.dispatchEvent(new Event('close')) }
  }
  const fetch = options.fetch || (async () => new Response(JSON.stringify({ access_token: 'token', voices: ['test-voice'] })))
  const context = vm.createContext({ console, setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
    Blob, FormData, Response, URL, AbortController, AbortSignal, DOMException, performance, document, window,
    WebSocket: Socket, fetch, localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) } })
  const source = await readFile(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: name }).content
  const module = new vm.SourceTextModule(script, { context })
  await module.link(specifier => {
    let values
    if (specifier === 'vue') values = Vue
    else if (specifier.endsWith('/session.js')) values = sessions
    else if (specifier.endsWith('/speechQueue.js')) values = queues
    else if (specifier.endsWith('/journey.js')) values = { ...journey, composeJourneyJournal: options.compose || journey.composeJourneyJournal }
    else if (specifier.endsWith('/api.js')) values = { WS_HOST: 'wss://test.invalid', boundedFetch: fetch }
    else if (specifier.endsWith('/store.js')) values = { store, setApiKey: k => { store.apiKey = k }, log() {}, dlog() {} }
    else if (specifier.endsWith('/audio.js')) values = { Mic, SR: 16000, wavEncode: () => new Blob(['wav']), fileToPCM: async () => new Int16Array(80000) }
    else if (specifier.endsWith('/journeyAudio.js')) values = { JourneySound: Sound, JourneyVoice: Voice, JourneyRecorder: Recorder, cleanJourneyVoices() {}, voiceFailureMessage: e => e.message }
    else values = { default: {} }
    return new vm.SyntheticModule(Object.keys(values), function () { for (const [k, v] of Object.entries(values)) this.setExport(k, v) }, { context })
  })
  await module.evaluate()
  const component = module.namespace.default
  component.render = () => null
  // A Vue renderer exercises real setup/watch/mount/unmount, without a microphone or network.
  const renderer = Vue.createRenderer({
    createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode() {}, nextSibling() {},
  })
  const active = Vue.ref(true)
  const app = renderer.createApp({ render: () => Vue.h(component, { active: active.value }) })
  app.mount({})
  const state = app._instance.subTree.component.setupState
  return { state, active, app, store, document, window, mics, sounds, voices, sockets, recorders }
}

for (const name of ['ModuleWorkbench', 'ModuleVoiceClone']) {
  test(`${name}: changing tabs cancels a pending connection`, async () => {
    const pending = deferred()
    const fixture = await mount(name, { fetch: async url => url.includes('ephemeral') ? pending.promise : new Response('{"voices":["test-voice"]}') })
    const { state, active, sockets, app } = fixture
    state.ambient = true; state.voiceSel = 'test-voice'
    const start = state.startSession()
    active.value = false; await Vue.nextTick()
    pending.resolve(new Response('{"access_token":"late"}'))
    await start
    assert.equal(state.running, false)
    assert.equal(sockets.length, 0)
    app.unmount()
  })
  test(`${name}: permission arriving after leaving releases microphone`, async () => {
    const permission = deferred()
    const { state, active, mics, app } = await mount(name, { permission })
    state.ambient = true; state.voiceSel = 'test-voice'
    const start = state.startSession(); await tick()
    assert.equal(mics.length, 1)
    active.value = false; await Vue.nextTick(); permission.resolve(); await start
    assert.equal(mics[0].stopped, true)
    assert.equal(state.running, false)
    app.unmount()
  })
  test(`${name}: first partial is visible and repeated final is idempotent`, async () => {
    const { state, app } = await mount(name)
    await state.appendTurn({ type: 'transcription.partial', segment_id: 1, text: '第一句话' })
    assert.equal(state.turns[0].text, '第一句话')
    const final = { type: 'transcription.final', segment_id: 1, text: '完整的一句话' }
    await state.appendTurn(final); await state.appendTurn(final)
    assert.equal(state.turns.length, 1)
    app.unmount()
  })
}

test('workbench records actual samples and cancels hidden enrollment', async () => {
  const { state, mics, active, app } = await mount('ModuleWorkbench')
  state.consent = true
  const recording = state.recordClip(); await tick()
  assert.ok(Array.isArray(mics[0].collection))
  mics[0].collection.push(new Int16Array(16000 * 5))
  active.value = false; await Vue.nextTick(); await recording
  assert.equal(state.clips.length, 0)
  assert.equal(mics[0].stopped, true)
  app.unmount()
})

test('clone synthesis resolving after stop never plays or revives the old queue', async () => {
  const pending = deferred()
  const { state, sounds, app } = await mount('ModuleVoiceClone', { fetch: async url => url.endsWith('/speech') ? pending.promise : new Response('{"voices":["test-voice"]}') })
  state.voiceSel = 'test-voice'
  const turn = { text: '给今天的自己一点勇气', voice: 'test-voice', speak: 'pending', sizeKB: 0 }
  const job = state.enqueueTTS(turn); await tick()
  await state.teardown(false)
  pending.resolve(new Response(new Blob(['late audio'])))
  await job
  assert.equal(sounds.reduce((n, s) => n + s.plays, 0), 0)
  app.unmount()
})

test('silence after speech completes the story, while resuming speech cancels the countdown', async () => {
  const { state, app, recorders } = await mount('BoothJourney', {
    compose: async draft => ({ ...draft, messageToSelf: '今天的小小想法，值得继续。', generation: 'model' }),
  })
  state.voiceEnabled = false
  await state.beginJourney()
  const { handlers } = recorders[0]
  handlers.onActivity(20, false)
  assert.equal(state.stage, 'listening')
  handlers.onText('我想设计一款提醒爸妈吃药的小工具。')
  handlers.onActivity(6, true)
  assert.equal(state.autoFinishSeconds, 2)
  handlers.onLevel(.2, true)
  assert.equal(state.autoFinishSeconds, 0)
  handlers.onActivity(0, true)
  assert.equal(state.stage, 'listening')
  handlers.onActivity(8, true)
  await tick()
  assert.equal(state.stage, 'preview')
  assert.equal(state.journal.originalText, '我想设计一款提醒爸妈吃药的小工具。')
  app.unmount()
})

test('journey replaces a rejected reference when the user records again', async () => {
  const { state, voices, app } = await mount('BoothJourney')
  const first = new Blob(['first']), next = new Blob(['new sample'])
  await state.prepareVoice(first)
  assert.equal(state.voiceState, 'failed')
  await state.prepareVoice(next)
  assert.equal(voices.length, 2)
  assert.equal(voices[0].disposed, true)
  assert.equal(voices[1].blob, next)
  app.unmount()
})

test('journey waits for Start, finishes its introduction, then opens recording', async () => {
  const intro = deferred()
  const recorderStart = deferred()
  const { state, recorders, app } = await mount('BoothJourney', { recorderStart, intro })
  await tick()
  assert.equal(state.stage, 'welcome')
  assert.equal(recorders.length, 0)
  const starting = state.beginJourney()
  assert.equal(state.stage, 'intro')
  assert.equal(recorders.length, 0)
  intro.resolve(true); await tick()
  assert.equal(state.stage, 'listening')
  assert.equal(state.connecting, true)
  assert.equal(recorders.length, 1)
  recorderStart.resolve()
  await starting
  assert.equal(state.recording, true)
  recorders[0].handlers.onAudio()
  assert.equal(state.audioCaptured, true)
  recorders[0].handlers.onText('我今天看到一个机器人。')
  assert.equal(state.topicId, 'future')
  assert.equal(state.text, '我今天看到一个机器人。')
  app.unmount()
  assert.ok(recorders[0].stopped)
})

test('skipping introduction opens exactly one recorder; late audio completion cannot restart it', async () => {
  const intro = deferred()
  const { state, recorders, app } = await mount('BoothJourney', { intro })
  const starting = state.beginJourney()
  await state.startListening()
  assert.equal(recorders.length, 1)
  intro.resolve(true); await starting
  assert.equal(recorders.length, 1)
  app.unmount()
})

test('leaving during introduction never opens the microphone later', async () => {
  const intro = deferred()
  const { state, recorders, active, app } = await mount('BoothJourney', { intro })
  const starting = state.beginJourney()
  active.value = false; await Vue.nextTick()
  intro.resolve(true); await starting
  assert.equal(recorders.length, 0)
  assert.equal(state.introPlaying, false)
  app.unmount()
})

test('failed introduction offers recovery without silently opening the microphone', async () => {
  const { state, recorders, app } = await mount('BoothJourney', { introError: true })
  await state.beginJourney()
  assert.equal(state.stage, 'intro')
  assert.ok(state.error.includes('播放'))
  assert.equal(recorders.length, 0)
  await state.startListening()
  assert.equal(recorders.length, 1)
  app.unmount()
})

test('text fallback opens the editor and late ASR events cannot overwrite it', async () => {
  const { state, recorders, app } = await mount('BoothJourney')
  state.useText()
  assert.equal(state.stage, 'listening')
  assert.equal(state.textMode, true)
  assert.equal(recorders.length, 0)
  state.reset()
  await state.beginJourney()
  recorders[0].handlers.onText('已识别的第一句话')
  state.useText()
  recorders[0].handlers.onText('迟到的识别')
  assert.equal(state.text, '已识别的第一句话')
  assert.ok(recorders[0].stopped)
  app.unmount()
})

test('finishing records the last ASR correction and advances to the generated note', async () => {
  const final = '我想给爸妈做一个吃药提醒工具。'
  const { state, recorders, app } = await mount('BoothJourney', {
    recorderFinal: final,
    compose: async draft => ({ ...draft, summary: final, messageToSelf: '先从一个提醒做起。', generation: 'model' }),
  })
  state.voiceEnabled = false
  await Vue.nextTick()
  await state.beginJourney()
  recorders[0].handlers.onAudio()
  assert.equal(state.text, '')
  await state.finishStory()
  assert.equal(state.stage, 'preview')
  assert.equal(state.journal.originalText, final)
  assert.equal(state.journal.topicId, 'future')
  assert.equal(state.journal.generation, 'model')
  assert.equal(state.recording, false)
  assert.equal(recorders.length, 1)
  assert.equal(recorders[0].stopped, true)
  recorders[0].handlers.onText('背景电视里的无关对话')
  assert.equal(state.journal.originalText, final)
  assert.equal(state.text, final)
  await state.listen()
  assert.equal(recorders.length, 1)
  app.unmount()
})

test('the cloned voice reads the complete short reply automatically and leaves the microphone off', async () => {
  const message = '你想做的，是让每句话都有人接得住。今天没改好，也别丢掉这个念头。'
  const { state, recorders, voices, sounds, app } = await mount('BoothJourney', {
    voiceAudio: new Blob(['test audio']),
    compose: async draft => ({ ...draft, summary: '我想让聊天接得更自然。', messageToSelf: message, generation: 'model' }),
  })
  await state.prepareVoice(new Blob(['test reference']))
  state.journal = journey.createJourneyJournal('我想试全双工，让聊天更自然。', 'future')
  await state.composeNote()
  assert.equal(voices[0].spoken, message)
  assert.equal(sounds[0].plays, 1)
  assert.equal(state.stage, 'preview')
  assert.equal(state.recording, false)
  assert.equal(recorders.length, 0)
  app.unmount()
})

test('reply generation and playback failures never open a result-page recorder', async () => {
  for (const failure of ['compose', 'voice', 'playback']) {
    const { state, recorders, app } = await mount('BoothJourney', {
      compose: async () => { throw new Error('text unavailable') },
      introError: true,
    })
    state.journal = { ...journey.createJourneyJournal('我想让爸爸搬东西省力一些。', 'future'), messageToSelf: '想让爸爸搬东西省些力，这份惦记值得留下。' }
    if (failure === 'compose') await state.composeNote()
    else if (failure === 'voice') await state.makeAudio(true)
    else { state.audioUrl = 'blob:test-only'; await state.replay() }
    assert.equal(state.stage, 'preview')
    assert.equal(state.recording, false)
    assert.equal(recorders.length, 0)
    assert.ok(state.error || state.voiceIssue)
    app.unmount()
  }
})

test('long speech is split without dropping characters; cancelled queues stay cancelled', async () => {
  const source = '这是一段需要完整保留的讲述。'.repeat(30)
  const parts = queues.speechChunks(source)
  assert.equal(parts.join(''), source)
  assert.ok(parts.every(part => Array.from(part).length <= 120))
  const pending = deferred(), seen = []
  const queue = new queues.SpeechQueue(() => {})
  queue.add(async () => { await pending.promise })
  const old = queue.add(async () => seen.push('old'))
  queue.reset()
  await queue.add(async () => seen.push('new'))
  pending.resolve(); await old
  assert.deepEqual(seen, ['new'])
})

test('backgrounding the journey during ASR finalization leaves a recoverable screen', async () => {
  const { state, document, app } = await mount('BoothJourney')
  state.stage = 'generating'; state.text = '已经说出的内容'
  document.hidden = true; document.dispatchEvent(new Event('visibilitychange'))
  assert.equal(state.stage, 'listening')
  assert.equal(state.text, '已经说出的内容')
  app.unmount()
})

test('closing print preview does not claim paper was delivered or reopen the microphone', async () => {
  const { state, window, recorders, app } = await mount('BoothJourney')
  let prints = 0
  window.print = () => { prints++ }
  state.journal = journey.createJourneyJournal('这是要留给未来的内容', 'story')
  await state.printJournal()
  assert.equal(prints, 1)
  assert.equal(state.stage, 'printing')
  window.dispatchEvent(new Event('afterprint'))
  assert.equal(state.printReturned, true)
  assert.equal(state.stage, 'printing')
  state.backToPreview()
  assert.equal(state.stage, 'preview')
  assert.equal(recorders.length, 0)
  app.unmount()
})
