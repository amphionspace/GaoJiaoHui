import test from 'node:test'
import assert from 'node:assert/strict'
import { SpeechGate } from '../src/core/journeySpeech.js'
import vm from 'node:vm'
import { readFile } from 'node:fs/promises'

async function warmModule(createDetector) {
  const context = vm.createContext({})
  const factory = new vm.SyntheticModule(['createDetector'], function () { this.setExport('createDetector', createDetector) }, { context })
  await factory.link(() => {})
  await factory.evaluate()
  const module = new vm.SourceTextModule(await readFile(new URL('../src/core/journeySpeech.js', import.meta.url), 'utf8'), {
    context, importModuleDynamically: () => factory,
  })
  await module.link(() => {})
  await module.evaluate()
  return module.namespace
}

test('greeting warmup is shared and transferring it to the recorder prevents premature disposal', async () => {
  let created = 0, disposed = 0
  const detector = { dispose() { disposed++ } }
  const speech = await warmModule(async () => { created++; return detector })
  assert.equal(speech.warmSpeechDetector(), speech.warmSpeechDetector())
  assert.equal(await speech.createSpeechDetector(), detector)
  speech.releasePreparedDetector()
  await Promise.resolve()
  assert.equal(created, 1)
  assert.equal(disposed, 0)
})

test('leaving an introduction releases a detector even if its loading finishes later', async () => {
  let finish, disposed = 0
  const speech = await warmModule(() => new Promise(resolve => { finish = resolve }))
  const warming = speech.warmSpeechDetector()
  await new Promise(resolve => setImmediate(resolve))
  speech.releasePreparedDetector()
  finish({ dispose() { disposed++ } })
  await warming
  await Promise.resolve()
  assert.equal(disposed, 1)
})

test('loud non-speech and short clicks do not pass the speech gate', () => {
  const gate = new SpeechGate(), output = []
  const emit = (pcm, speaking) => output.push({ pcm, speaking })
  for (let i = 0; i < 350; i++) gate.push(new Int16Array(512).fill(12000), i === 100 ? .99 : .1, emit)
  gate.flush(emit)
  assert.ok(output.every(frame => !frame.speaking && frame.pcm.every(value => value === 0)))
})

test('speech preserves its onset and returns to silence despite loud background noise', () => {
  const gate = new SpeechGate(), output = []
  const emit = (pcm, speaking) => output.push({ pcm, speaking })
  for (let i = 0; i < 40; i++) gate.push(new Int16Array(512).fill(i < 10 ? 100 : 1200), i < 10 ? .05 : .95, emit)
  for (let i = 0; i < 300; i++) gate.push(new Int16Array(512).fill(15000), .05, emit)
  gate.flush(emit)
  assert.ok(output.some(frame => frame.speaking && frame.pcm[0] === 1200))
  assert.ok(output.slice(-250).every(frame => !frame.speaking && frame.pcm[0] === 0))
})
