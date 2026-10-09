<script setup>
/* 接口一：流式转写 WS /asr/v1/realtime（api_key 直连）
   - delta 全量累积文本直接覆盖上屏；commit{final:true} 出最终全文与计费
   - 前端 VAD 自动判停（RMS>0.015、最小说话 0.8s、静音 N 秒可调、3s 倒计时可取消）
   - 自动流转：done 后 0.6s emit -> App 切接口二并自动开录 */
import { ref, onBeforeUnmount } from 'vue'
import { WS_HOST } from '../core/api.js'
import { store, log, dlog } from '../core/store.js'
import { SR, FRAME, Mic, fileToPCM, streamPCM, b64frame } from '../core/audio.js'
import { createVad } from '../core/vad.js'

const emit = defineEmits(['autoFlow'])

const recording = ref(false)
const stTxt = ref('空闲')
const partial = ref('（实时转写会显示在这里…）')
const finalText = ref(''), finalMeta = ref(''), finalShow = ref(false)
const autoFlow = ref(true)
const vadSilence = ref(2.5)
const countdown = ref(null)          // 倒计时剩余秒（null=未触发）
const fileInput = ref(null)

let ws1 = null, mic1 = null, stopFlag1 = false, t1 = 0, autoTimer = null, sentFrames1 = 0

const vad = createVad({
  silenceSec: () => Math.min(10, Math.max(1, parseFloat(vadSilence.value) || 2.5)),
  enabled: () => autoFlow.value,
  armed: () => autoTimer !== null,
  onTrigger: triggerAutoFinish
})

function triggerAutoFinish() {
  countdown.value = 3
  log('一 检测到停顿（静音 ' + vadSilence.value + 's），3 秒后自动收尾', 'evt')
  autoTimer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) { cancelAutoFinish(); stopRealtime(); return }
  }, 1000)
}
function cancelAutoFinish() {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null }
  countdown.value = null
}
function setUI(rec) { recording.value = rec; stTxt.value = rec ? '录音中' : '空闲' }

async function startRealtime(source, file) {
  if (ws1) return
  finalShow.value = false; partial.value = '（连接中…）'
  setUI(true); stopFlag1 = false; t1 = Date.now(); sentFrames1 = 0
  cancelAutoFinish(); vad.reset()
  try {
    const ws = new WebSocket(`${WS_HOST}/asr/v1/realtime?api_key=${encodeURIComponent(store.apiKey)}`)
    ws1 = ws
    ws.onopen = async () => {
      log('一 WS 已连接（api_key 直连）', 'ok')
      ws.send(JSON.stringify({type: 'session.update', session: {language: 'auto'}}))
      const sendJSON = f => { if (ws.readyState === 1) { sentFrames1++
        ws.send(JSON.stringify({type: 'input_audio_buffer.append', audio: b64frame(f)})) } }
      if (source === 'mic') {
        mic1 = new Mic()
        mic1.start(pcm => { vad.feed(pcm)
          for (let i = 0; i < pcm.length; i += FRAME) sendJSON(pcm.subarray(i, i + FRAME)) })
          .catch(e => { log('一 麦克风失败: ' + e.message, 'err')
            partial.value = '（麦克风不可用——排查见事件日志；可先用「音频文件测试」）'; stopRealtime() })
      } else {
        log('一 文件解码: ' + file.name)
        const pcm = await fileToPCM(file)
        stTxt.value = `回放中（${(pcm.length / SR).toFixed(1)}s）`
        await streamPCM(pcm, sendJSON, () => stopFlag1)
        if (!stopFlag1) stopRealtime()      // 文件播完自动收尾
      }
    }
    ws.onmessage = ev => {
      let d; try { d = JSON.parse(ev.data) } catch (e) { return }
      const t = d.type || ''
      if (t === 'transcription.delta') {
        partial.value = d.text || d.delta || ''                 // 全量累积，直接覆盖
      } else if (t === 'transcription.done') {
        finalShow.value = true; finalText.value = d.text || ''
        const secs = d.usage && d.usage.seconds ? d.usage.seconds.toFixed(1) : '?'
        finalMeta.value = `计费时长 ${secs}s · 端到端耗时 ${((Date.now() - t1) / 1000).toFixed(1)}s`
        log('一 done: ' + (d.text || ''), 'ok')
        if (autoFlow.value) setTimeout(() => emit('autoFlow'), 600)   // 电话亭自动流转
      } else if (t === 'error') {
        log('一 服务端错误: ' + JSON.stringify(d), 'err')
      } else if (t !== 'transcription.partial') {
        dlog('一 EVT: ' + JSON.stringify(d).slice(0, 300), 'evt')
      }
    }
    ws.onclose = ev => { log(`一 WS 关闭 (${ev.code}${ev.reason ? ' ' + ev.reason : ''})`); cleanup() }
    ws.onerror = () => log('一 WS 错误', 'err')
  } catch (e) { log('一 ' + e.message, 'err'); cleanup() }
}

function stopRealtime() {
  cancelAutoFinish(); stopFlag1 = true
  if (mic1) { mic1.stop(); mic1 = null }
  if (ws1 && ws1.readyState === 1) {
    if (sentFrames1 > 0) {
      ws1.send(JSON.stringify({type: 'input_audio_buffer.commit', final: true}))
    } else {                                  // 零音频帧（如麦克风失败）：不发 commit 直接关闭，避免服务端 "No audio data received."
      log('一 本次会话未发送任何音频帧，直接关闭（不发 commit）', 'evt')
      ws1.close()
    }
  }
  setUI(false)
}
function cleanup() { if (mic1) { mic1.stop(); mic1 = null } ws1 = null; setUI(false) }
function pickFile() { fileInput.value && fileInput.value.click() }
function onFile(e) { const f = e.target.files[0]; if (f) startRealtime('file', f); e.target.value = '' }
onBeforeUnmount(() => { cancelAutoFinish(); cleanup() })
</script>

<template>
  <section class="card">
    <h2>接口一 流式转写
      <span class="tag">WS /asr/v1/realtime</span><span class="tag">JSON·base64 音频帧</span></h2>
    <div class="desc">录音实时上屏；每次 <code>transcription.delta</code> 携带<b>全量累积文本</b>（停顿修正），
      松开/停止后 <code>commit{final:true}</code> 出最终全文与计费时长。也可选本地音频文件按 1× 速率回放测试。</div>
    <div class="row">
      <button class="act" :disabled="recording" @click="startRealtime('mic')">开始录音</button>
      <button class="act stop" :disabled="!recording" @click="stopRealtime()">结束并出全文</button>
      <label class="act ghost" style="display:inline-block">音频文件测试
        <input type="file" accept="audio/*" style="display:none" ref="fileInput" @change="onFile"></label>
      <label class="sub" style="display:inline-flex;gap:4px;align-items:center;cursor:pointer">
        <input type="checkbox" v-model="autoFlow">自动流转</label>
      <label class="sub" style="display:inline-flex;gap:4px;align-items:center">静音判停
        <input type="number" v-model="vadSilence" min="1" max="10" step="0.5" style="width:52px">秒</label>
      <button v-if="countdown !== null" class="mini" @click="cancelAutoFinish()">取消自动收尾</button>
      <span class="sub">{{ countdown !== null ? `检测到停顿，${countdown} 秒后自动结束并进入多人分离…` : stTxt }}</span>
    </div>
    <div style="font-size:19px;line-height:1.7;min-height:58px;padding:12px;background:var(--panel2);
      border-radius:10px;border:1px dashed #c6ccd6">{{ partial }}</div>
    <div v-if="finalShow" style="margin-top:12px;padding:14px;border-radius:10px;
      background:rgba(23,138,76,.05);border:1px solid rgba(23,138,76,.35)">
      <div style="font-size:18px;line-height:1.7">{{ finalText }}</div>
      <div class="meta">{{ finalMeta }}</div>
    </div>
  </section>
</template>
