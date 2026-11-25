import test from 'node:test'
import assert from 'node:assert/strict'
import { anySignal, timeoutSignal, withTimeout } from '../src/core/abortSignals.js'

function without(name, run) {
  const original = Object.getOwnPropertyDescriptor(AbortSignal, name)
  Object.defineProperty(AbortSignal, name, { value: undefined, configurable: true, writable: true })
  try {
    return run()
  } finally {
    Object.defineProperty(AbortSignal, name, original)
  }
}

test('anySignal aborts as soon as one input aborts', () => {
  const first = new AbortController()
  const second = new AbortController()
  const merged = anySignal([first.signal, second.signal])
  assert.equal(merged.aborted, false)
  second.abort(new Error('stop'))
  assert.equal(merged.aborted, true)
})

test('anySignal falls back when the browser has no AbortSignal.any', async () => {
  await without('any', async () => {
    const parent = new AbortController()
    const merged = anySignal([parent.signal, new AbortController().signal])
    assert.equal(merged.aborted, false)
    parent.abort(new Error('cancelled'))
    assert.equal(merged.aborted, true)
    assert.equal(merged.reason.message, 'cancelled')
  })
})

test('anySignal passes an already-aborted signal through', async () => {
  await without('any', async () => {
    const parent = new AbortController()
    parent.abort(new Error('early'))
    const merged = anySignal([parent.signal])
    assert.equal(merged.aborted, true)
    assert.equal(merged.reason.message, 'early')
  })
})

test('timeoutSignal aborts with a TimeoutError', async () => {
  const signal = timeoutSignal(10)
  await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }))
  assert.equal(signal.reason.name, 'TimeoutError')
})

test('withTimeout keeps the caller signal and adds the deadline', () => {
  const parent = new AbortController()
  const merged = withTimeout(parent.signal, 5000)
  parent.abort(new Error('user cancelled'))
  assert.equal(merged.aborted, true)
  assert.equal(merged.reason.message, 'user cancelled')
})
