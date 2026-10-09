<script setup>
/* 接口二：多人说话人分离 WS /asr/v1/target-dialogue（二进制 PCM 帧 · open 模式）
   优先 ephemeral token（一次性 JWT），失败退回 ?api_key= 直连。
   partial -> pending 气泡（正在确认说话人），final -> role_index 着色气泡 */
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { WS_HOST, api, getEphemeralToken } from '../core/api.js'
import { store, log, dlog } from '../core/store.js'
import { SR, FRAME, Mic, fileToPCM, streamPCM } from '../core/audio.js'

const SPK_COLORS = ['var(--spk1)', 'var(--spk2)', 'var(--spk3)', 'var(--spk4)']

const recording = ref(false)
const stTxt = ref('空闲')
const bubbles = ref([])          // { seg, pending, text, who, color }
const doneInfo = ref('')
const bubblesBox = ref(null)
const fileInput = ref(null)

let ws2 = null, mic2 = null, stopFlag2 = false, sentFrames2 = 0

function setUI(rec) { recording.value = rec; stTxt.value = rec ? '录音中' : '空闲' }

async function scrollBottom() { await nextTick(); if (bubblesBox.value) bubblesBox.value.scrollTop = 1e9 }

function bubble(d, pending) {
  const seg = d.segment_id || ('seg-' + Date.now())
  if (pending) {
    const cur = bubbles.value[bubbles.value.length - 1]
    if (cur && cur.seg === seg && cur.pending) { cur.text = d.text || ''; scrollBottom(); return }
  }
  const who = pending ? '正在确认说话人…'
    : `说话人 ${(d.role_index || 0) + 1}${d.speaker_name && d.speaker_name !== 'null' ? ' · ' + d.speaker_name : ''}`
  const color = pending ? 'var(--dim)' : SPK_COLORS[(d.role_index || 0) % SPK_COLORS.length]
  bubbles.value.push({ seg, pending, text: d.text || '', who, color })
  scrollBottom()
}

async function start(source, file) {
  if (ws2) return
  bubbles.value = []; doneInfo.value = ''
  setUI(true); stopFlag2 = false; sentFrames2 = 0
  try {
    let token = null
    try { token = await getEphemeralToken(); dlog('二 ephemeral token 已签发（经本地代理）', 'ok') }
    catch (e) { dlog('二 token 签发失败（' + e.message + '），退回 ?api_key= 直连', 'evt') }
    const ws = new WebSocket(`${WS_HOST}/asr/v1/target-dialogue${token ? '' : '?api_key=' + encodeURIComponent(store.apiKey)}`)
    ws2 = ws
    ws.onopen = async () => {
      log('二 WS 已连接（' + (token ? 'token' : 'api_key') + ' 模式）', 'ok')
      if (token) ws.send(JSON.stringify({type: 'session.authenticate', access_token: token}))
      ws.send(JSON.stringify({type: 'session.update', session: {
        filter: {mode: 'open'},
        participants: [],
        audio: {sample_rate_hz: SR},
        recognition: {mode: 'role_separation'}}}))
      const sendBin = f => { if (ws.readyState === 1) { sentFrames2++
        ws.send(new Uint8Array(f.buffer, f.byteOffset, f.byteLength)) } }
      if (source === 'mic') {
        mic2 = new Mic()
        mic2.start(pcm => { for (let i = 0; i < pcm.length; i += FRAME) sendBin(pcm.subarray(i, i + FRAME)) })
          .catch(e => { log('二 麦克风失败: ' + e.message + '；可改用「音频文件测试」', 'err'); stop() })
      } else {
        log('二 文件解码: ' + file.name)
        const pcm = await fileToPCM(file)
        stTxt.value = `回放中（${(pcm.length / SR).toFixed(1)}s）`
        await streamPCM(pcm, sendBin, () => stopFlag2)
        if (!stopFlag2) stop()
      }
    }
    ws.onmessage = ev => {
      let d; try { d = JSON.parse(ev.data) } catch (e) { return }
      const t = d.type || ''
      if (t === 'transcription.partial') bubble(d, true)
      else if (t === 'transcription.final') { bubble(d, false); log('二 final: ' + (d.text || ''), 'ok') }
      else if (t === 'session.done') {
        const s = d.duration_seconds
        doneInfo.value = `会话完成 · 时长 ${typeof s === 'number' ? s.toFixed(1) : s}s · 识别角色 ${d.identified_roles} · 压制 ${d.suppressed_roles}`
      }
      else if (t === 'error') log('二 服务端错误: ' + JSON.stringify(d), 'err')
      else dlog('二 EVT: ' + JSON.stringify(d).slice(0, 300), 'evt')
    }
    ws.onclose = ev => { log(`二 WS 关闭 (${ev.code})`); cleanup() }
    ws.onerror = () => log('二 WS 错误', 'err')
  } catch (e) { log('二 ' + e.message, 'err'); cleanup() }
}

function stop() {
  stopFlag2 = true
  if (mic2) { mic2.stop(); mic2 = null }
  if (ws2 && ws2.readyState === 1) {
    if (sentFrames2 > 0) {
      ws2.send(JSON.stringify({type: 'input_audio_buffer.commit', final: true}))
    } else {                                  // 零音频帧：不发 commit 直接关闭，避免服务端 "No audio data received."
      log('二 本次会话未发送任何音频帧，直接关闭（不发 commit）', 'evt')
      ws2.close()
    }
  }
  setUI(false)
}
function cleanup() { if (mic2) { mic2.stop(); mic2 = null } ws2 = null; setUI(false) }
function pickFile() { fileInput.value && fileInput.value.click() }
function onFile(e) { const f = e.target.files[0]; if (f) start('file', f); e.target.value = '' }
onBeforeUnmount(cleanup)
defineExpose({ start })
</script>

<template>
  <section class="card">
    <h2>接口二 多人说话人分离
      <span class="tag">WS /asr/v1/target-dialogue</span><span class="tag">二进制 PCM 帧</span><span class="tag">open 模式</span></h2>
    <div class="desc">优先经本地代理申请 <b>ephemeral token</b>（一次性 JWT，浏览器免长期 Key），失败自动退回
      <code>?api_key=</code> 直连。每个 <code>transcription.final</code> 为一个说话人气泡（role_index 着色）。</div>
    <div class="row">
      <button class="act" :disabled="recording" @click="start('mic')">开始录音</button>
      <button class="act stop" :disabled="!recording" @click="stop()">结束</button>
      <label class="act ghost" style="display:inline-block">音频文件测试
        <input type="file" accept="audio/*" style="display:none" ref="fileInput" @change="onFile"></label>
      <span class="sub">{{ stTxt }}</span>
    </div>
    <div ref="bubblesBox" style="display:flex;flex-direction:column;gap:8px;max-height:340px;overflow-y:auto;padding:4px">
      <div v-for="(b, i) in bubbles" :key="i" class="bub-item"
        :style="{maxWidth:'78%',padding:'9px 13px',borderRadius:'12px',background:'#fff',
          border:'1px solid var(--line)',lineHeight:'1.6',opacity: b.pending ? .65 : 1,
          fontStyle: b.pending ? 'italic' : 'normal'}">
        <div style="font-size:11px;margin-bottom:3px;font-weight:600" :style="{color: b.color}">{{ b.who }}</div>
        <div style="font-size:15px">{{ b.text }}</div>
      </div>
    </div>
    <div class="meta">{{ doneInfo }}</div>
  </section>
</template>
