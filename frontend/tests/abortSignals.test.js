import test from 'node:test'
import assert from 'node:assert/strict'
import { anySignal, timeoutSignal, withTimeout } from '../src/core/abortSignals.js'

// Passing an object without the static methods exercises the fallback path
// without mutating the global AbortSignal (CI may freeze it).
const NO_STATICS = {}

test('anySignal aborts as soon as one input aborts', () => {
  for (const Signal of [undefined, NO_STATICS]) {
    const first = new AbortController()
    const second = new AbortController()
    const merged = Signal ? anySignal([first.signal, second.signal], Signal) : anySignal([first.signal, second.signal])
    assert.equal(merged.aborted, false)
    second.abort(new Error('stop'))
    assert.equal(merged.aborted, true)
  }
})

test('anySignal passes an already-aborted signal through', () => {
  for (const Signal of [undefined, NO_STATICS]) {
    const parent = new AbortController()
    parent.abort(new Error('early'))
    const merged = Signal ? anySignal([parent.signal], Signal) : anySignal([parent.signal])
    assert.equal(merged.aborted, true)
    assert.equal(merged.reason.message, 'early')
  }
})

test('timeoutSignal aborts with a TimeoutError', async () => {
  for (const Signal of [undefined, NO_STATICS]) {
    const signal = Signal ? timeoutSignal(10, Signal) : timeoutSignal(10)
    await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }))
    assert.equal(signal.reason.name, 'TimeoutError')
  }
})

test('withTimeout keeps the caller signal and adds the deadline', () => {
  for (const Signal of [undefined, NO_STATICS]) {
    const parent = new AbortController()
    const merged = Signal ? withTimeout(parent.signal, 5000, Signal) : withTimeout(parent.signal, 5000)
    parent.abort(new Error('user cancelled'))
    assert.equal(merged.aborted, true)
    assert.equal(merged.reason.message, 'user cancelled')
  }
})
