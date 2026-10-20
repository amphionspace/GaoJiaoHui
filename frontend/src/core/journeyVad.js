import * as ort from 'onnxruntime-web/wasm'
import { Silero } from '@ricky0123/vad-web/dist/models/silero.js'
import modelUrl from '@ricky0123/vad-web/dist/silero_vad_v5.onnx?url'
import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url'
import { SpeechGate } from './journeySpeech.js'

ort.env.wasm.numThreads = 1
ort.env.wasm.wasmPaths = { wasm: wasmUrl }

export async function createDetector() {
  const model = await Silero.new(ort, async () => {
    const response = await fetch(modelUrl)
    if (!response.ok) throw new Error('人声检测未能加载，请刷新页面后重试。')
    return response.arrayBuffer()
  })
  const gate = new SpeechGate()
  let tail = new Int16Array(0)
  return {
    async process(pcm, emit) {
      const input = new Int16Array(tail.length + pcm.length)
      input.set(tail); input.set(pcm, tail.length)
      let offset = 0
      for (; offset + 512 <= input.length; offset += 512) {
        const frame = input.slice(offset, offset + 512)
        const result = await model.process(Float32Array.from(frame, value => value / 32768))
        gate.push(frame, result.isSpeech, emit)
      }
      tail = input.slice(offset)
    },
    async flush(emit) {
      if (tail.length) {
        const frame = new Int16Array(512); frame.set(tail); tail = new Int16Array(0)
        const result = await model.process(Float32Array.from(frame, value => value / 32768))
        gate.push(frame, result.isSpeech, emit)
      }
      gate.flush(emit)
    },
    dispose() { return model.release() },
  }
}
