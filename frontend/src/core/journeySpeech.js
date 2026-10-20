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

export async function createSpeechDetector() {
  const { createDetector } = await import('./journeyVad.js')
  return createDetector()
}
