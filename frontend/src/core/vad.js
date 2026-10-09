/* 前端 VAD 自动判停（电话亭反馈 1）：RMS 能量状态机
   说过话（累计 >=0.8s 且 RMS>0.015）后静音超阈值 -> 触发 onTrigger */
export function createVad({ silenceSec = () => 2.5, enabled = () => true, armed = () => false, onTrigger }) {
  let st = { hasSpeech: false, speechMs: 0, silenceMs: 0 }
  return {
    reset() { st = { hasSpeech: false, speechMs: 0, silenceMs: 0 } },
    feed(pcm) {
      if (!enabled() || armed()) return
      let sum = 0; for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i]
      const rms = Math.sqrt(sum / pcm.length) / 32768, durMs = pcm.length / 16000 * 1000
      if (rms > 0.015) {
        st.speechMs += durMs; st.silenceMs = 0
        if (!st.hasSpeech && st.speechMs >= 800) st.hasSpeech = true
      } else if (st.hasSpeech) {
        st.silenceMs += durMs
        if (st.silenceMs >= silenceSec() * 1000) onTrigger()
      }
    }
  }
}
