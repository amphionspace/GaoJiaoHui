import test from 'node:test'
import assert from 'node:assert/strict'
import { anySignal, timeoutSignal, withTimeout } from '../src/core/abortSignals.js'

// An object without the statics exercises the fallback path; the real
// AbortSignal is never mutated, so the tests behave the same on every Node.
const NO_STATICS = {}

test('uses the platform helpers when the browser has them', () => {
  const calls = []
  const Signal = {
    any: signals => { calls.push('any'); return signals[0] },
    timeout: milliseconds => { calls.push('timeout:' + milliseconds); return new AbortController().signal },
  }
  const parent = new AbortController()
  anySignal([parent.signal], Signal)
  withTimeout(parent.signal, 20, Signal)
  assert.deepEqual(calls, ['any', 'timeout:20', 'any'])
})

test('fallback anySignal aborts as soon as one input aborts', () => {
  const first = new AbortController()
  const second = new AbortController()
  const merged = anySignal([first.signal, second.signal], NO_STATICS)
  assert.equal(merged.aborted, false)
  second.abort(new Error('stop'))
  assert.equal(merged.aborted, true)
})

test('fallback anySignal passes an already-aborted signal through', () => {
  const parent = new AbortController()
  parent.abort(new Error('early'))
  const merged = anySignal([parent.signal], NO_STATICS)
  assert.equal(merged.aborted, true)
  assert.equal(merged.reason.message, 'early')
})

test('fallback timeoutSignal aborts with a TimeoutError', async () => {
  const signal = timeoutSignal(20, NO_STATICS)
  await new Promise((resolve, reject) => {
    const guard = setTimeout(() => reject(new Error('the timeout never fired')), 2000)
    signal.addEventListener('abort', () => { clearTimeout(guard); resolve() }, { once: true })
  })
  assert.equal(signal.reason.name, 'TimeoutError')
})

test('fallback withTimeout keeps the caller signal', () => {
  const parent = new AbortController()
  const merged = withTimeout(parent.signal, 20, NO_STATICS)
  parent.abort(new Error('user cancelled'))
  assert.equal(merged.aborted, true)
  assert.equal(merged.reason.message, 'user cancelled')
})
