// AbortSignal.any() arrived in Chrome 116 and AbortSignal.timeout() in 103.
// The booth may run on an older Chrome (Windows 7 caps at 109), so both calls
// go through these fallbacks instead of failing with "is not a function".

export function timeoutSignal(milliseconds) {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(milliseconds)
  }
  const controller = new AbortController()
  const timer = setTimeout(() => {
    controller.abort(new DOMException('The operation timed out.', 'TimeoutError'))
  }, milliseconds)
  // Do not keep the page alive just for the timer.
  timer?.unref?.()
  return controller.signal
}

export function anySignal(signals) {
  const list = (signals || []).filter(Boolean)
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.any === 'function') {
    return AbortSignal.any(list)
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

export function withTimeout(signal, milliseconds) {
  return signal ? anySignal([signal, timeoutSignal(milliseconds)]) : timeoutSignal(milliseconds)
}
