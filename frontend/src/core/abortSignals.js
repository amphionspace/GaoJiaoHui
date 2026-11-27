// AbortSignal.any() arrived in Chrome 116 and AbortSignal.timeout() in 103.
// The booth may run on an older Chrome (Windows 7 caps at 109), so both calls
// go through these fallbacks instead of failing with "is not a function".
// The Signal argument exists so tests can exercise the fallback without
// replacing the global AbortSignal.

const GLOBAL_SIGNAL = typeof AbortSignal === 'undefined' ? undefined : AbortSignal

export function timeoutSignal(milliseconds, Signal = GLOBAL_SIGNAL) {
  if (Signal && typeof Signal.timeout === 'function') {
    return Signal.timeout(milliseconds)
  }
  const controller = new AbortController()
  const timer = setTimeout(() => {
    controller.abort(new DOMException('The operation timed out.', 'TimeoutError'))
  }, milliseconds)
  // Do not keep the page alive just for the timer.
  timer?.unref?.()
  return controller.signal
}

export function anySignal(signals, Signal = GLOBAL_SIGNAL) {
  const list = (signals || []).filter(Boolean)
  if (Signal && typeof Signal.any === 'function') {
    return Signal.any(list)
  }
  const controller = new AbortController()
  for (const signal of list) {
    if (signal.aborted) {
      controller.abort(signal.reason)
      break
    }
    signal.addEventListener('abort', () => controller.abort(signal.reason), { once: true })
  }
  return controller.signal
}

export function withTimeout(signal, milliseconds, Signal = GLOBAL_SIGNAL) {
  return signal
    ? anySignal([signal, timeoutSignal(milliseconds, Signal)], Signal)
    : timeoutSignal(milliseconds, Signal)
}
