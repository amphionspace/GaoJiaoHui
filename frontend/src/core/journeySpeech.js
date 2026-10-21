// Audio stays local until the speech detector has identified a spoken segment.
export class SpeechGate {
  constructor() {
    this.pending = []; this.positive = 0; this.quiet = 0; this.active = false
  }
  push(pcm, probability, emit) {
    const seconds = pcm.length / 16000
    if (probability >= .6) this.positive += seconds
    else this.positive = 0
    if (this.positive >= .16) this.active = true
    if (probability >= .35) this.quiet = 0
    else this.quiet += seconds
    if (this.quiet >= .48) this.active = false
    this.pending.push({ pcm, voiced: probability >= .6 })
    if (this.pending.length > 10) this.emitFrame(this.pending.shift(), emit)
  }
  emitFrame(frame, emit) {
    emit(this.active ? frame.pcm : new Int16Array(frame.pcm.length), this.active, this.active && frame.voiced)
  }
  flush(emit) { for (const frame of this.pending) this.emitFrame(frame, emit); this.pending = [] }
}

let preparedDetector = null
async function loadDetector() {
  const { createDetector } = await import('./journeyVad.js')
  return createDetector()
}

// Warm only the local detector during the greeting; microphone access waits for it to end.
export function warmSpeechDetector() {
  if (!preparedDetector) {
    const pending = preparedDetector = loadDetector()
    pending.catch(() => { if (preparedDetector === pending) preparedDetector = null })
  }
  return preparedDetector
}
export function releasePreparedDetector() {
  const pending = preparedDetector
  preparedDetector = null
  pending?.then(detector => detector.dispose()).catch(() => {})
}
export function createSpeechDetector() {
  const pending = preparedDetector || loadDetector()
  preparedDetector = null
  return pending
}
