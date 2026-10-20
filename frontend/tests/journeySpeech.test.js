import test from 'node:test'
import assert from 'node:assert/strict'
import { SpeechGate } from '../src/core/journeySpeech.js'

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
