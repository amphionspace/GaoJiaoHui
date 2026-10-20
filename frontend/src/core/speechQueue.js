export function speechChunks(text, limit = 120) {
  const chunks = []
  let rest = Array.from(text.trim())
  while (rest.length) {
    let end = Math.min(limit, rest.length)
    if (end < rest.length) {
      const boundary = rest.slice(0, end).join('').search(/[。！？；，,.!?;][^。！？；，,.!?;]*$/)
      if (boundary >= end / 2) end = boundary + 1
    }
    chunks.push(rest.splice(0, end).join(''))
  }
  return chunks
}

// Each queue owns a cancellation signal. A previous session can never resume it.
export class SpeechQueue {
  constructor(stop) { this.stop = stop; this.reset() }
  reset() {
    this.cancel()
    this.controller = new AbortController()
    this.chain = Promise.resolve()
    this.pending = 0
  }
  cancel() { this.controller?.abort(); this.stop?.() }
  add(work) {
    const signal = this.controller.signal
    if (signal.aborted) return Promise.resolve(false)
    if (this.pending >= 10) return Promise.reject(new Error('待播放内容较多，请稍后重试这一句。'))
    this.pending++
    const result = this.chain.then(() => signal.aborted ? false : work(signal))
    this.chain = result.catch(() => {}).finally(() => { if (signal === this.controller.signal) this.pending-- })
    return result
  }
}
