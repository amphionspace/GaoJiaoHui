<script setup>
/* 接口三：声纹注册（A）+ 克隆合成（B）
   A: 录 2-15s 参考音频/选文件 -> multipart POST /tts/v1/audio/voices（火山 Seed-ICL 2.0，配额 10）
   B: 合成后端可选 —— qwen-tts-1.7b（本地 vLLM，model 名直通路由，~1s）/ seed-iclv2（火山） */
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../core/api.js'
import { log } from '../core/store.js'
import { SR, Mic, fileToPCM, wavEncode } from '../core/audio.js'
import WaveCanvas from './WaveCanvas.vue'

const recBtn = ref('开始录制')
const recTimerTxt = ref('')
const recInfo = ref('未录制')
const voiceName = ref('')
const cloneSt = ref('')
const cloneResult = ref('')
const cloneBusy = ref(false)
const chunks = ref([])
const refFileInput = ref(null)

const voices = ref([])
const voiceSel = ref('')
const voicesNote = ref('')
const ttsModel = ref('qwen-tts-1.7b')
const ttsText = ref('本地网页克隆合成验证，成功。')
const ttsSt = ref('')
const player = ref(null)

let recMic = null, recTimer = null, recStart = 0, refBlob = null

async function toggleRec() {
  if (recMic) {                                  // 停止
    clearInterval(recTimer); recMic.stop(); recMic = null
    const dur = chunks.value.reduce((s, c) => s + c.length, 0) / SR
    recBtn.value = '开始录制'; recTimerTxt.value = ''
    if (dur < 1) { recInfo.value = '太短（<1s），请重录'; refBlob = null; return }
    refBlob = wavEncode(chunks.value)
    recInfo.value = `已录 ${dur.toFixed(1)}s · ${(refBlob.size / 1024).toFixed(0)}KB WAV`
    log(`三 参考音频已就绪（${dur.toFixed(1)}s）`, 'ok')
    return
  }
  chunks.value = []; refBlob = null
  recMic = new Mic()
  try { await recMic.start(() => {}, chunks.value) }
  catch (e) { recMic = null; recInfo.value = '麦克风失败：' + e.message; return }
  recBtn.value = '停止录制'; recStart = Date.now()
  recTimer = setInterval(() => { const s = (Date.now() - recStart) / 1000
    recTimerTxt.value = s.toFixed(1) + 's' + (s > 15 ? '（已超 15s，请停止）' : '') }, 100)
}

async function onRefFile(f) {
  try {
    const pcm = await fileToPCM(f)
    refBlob = wavEncode([pcm]); chunks.value = [pcm]
    recInfo.value = `文件 ${f.name} · ${(pcm.length / SR).toFixed(1)}s · ${(refBlob.size / 1024).toFixed(0)}KB`
    log(`三 参考文件已解码（${(pcm.length / SR).toFixed(1)}s）`, 'ok')
  } catch (e) { recInfo.value = '解码失败：' + e.message; log('三 文件解码失败: ' + e.message, 'err') }
}

function pickRefFile() { refFileInput.value && refFileInput.value.click() }
function onRefFileInput(e) { const f = e.target.files[0]; if (f) onRefFile(f); e.target.value = '' }

async function cloneVoice() {
  const name = voiceName.value.trim()
  if (!refBlob) return log('三 请先录制或选择参考音频', 'err')
  if (!/^[A-Za-z0-9_\-]{1,64}$/.test(name)) return log('三 音色名需为英文/数字/下划线', 'err')
  cloneSt.value = '上传复刻中…'; cloneBusy.value = true
  const t0 = performance.now()
  try {
    const fd = new FormData()
    fd.append('voice_name', name)
    fd.append('audio_file', refBlob, name + '.wav')
    const r = await api('/tts/v1/audio/voices', {method: 'POST', body: fd})
    const dt = ((performance.now() - t0) / 1000).toFixed(1)
    cloneResult.value = `注册成功（耗时 ${dt}s）：` + JSON.stringify(r).slice(0, 400)
    log('三 clone: ' + JSON.stringify(r).slice(0, 300), 'ok')
    listVoices(name)
  } catch (e) {
    cloneResult.value = '失败：' + e.message
    log('三 clone 失败: ' + e.message, 'err')
  }
  cloneSt.value = ''; cloneBusy.value = false
}

async function listVoices(prefer) {
  try {
    const r = await api('/tts/v1/audio/voices')
    const list = r.voices || r.items || (Array.isArray(r) ? r : [])
    voices.value = list.map(v => v.voice_name || v.name || v)
    if (prefer && voices.value.includes(prefer)) voiceSel.value = prefer
    else if (!voiceSel.value && voices.value.length) voiceSel.value = voices.value[0]
    voicesNote.value = `共 ${voices.value.length} 个音色（账号配额 10）。含系统音色与已克隆音色。`
    log(`三 音色列表 ${voices.value.length} 个已刷新`, 'ok')
  } catch (e) { log('三 列表失败: ' + e.message, 'err') }
}

async function speak() {
  const voice = voiceSel.value, text = ttsText.value.trim()
  if (!voice) return log('三 请先刷新并选择音色', 'err')
  if (!text) return log('三 请输入合成文本', 'err')
  ttsSt.value = '合成中…'
  const t0 = performance.now()
  try {
    const blob = await api('/tts/v1/audio/speech', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: ttsModel.value, voice: voice, input: text,
        response_format: 'wav', sample_rate: 24000})})
    const dt = ((performance.now() - t0) / 1000).toFixed(1)
    player.value.src = URL.createObjectURL(blob)
    player.value.play()
    ttsSt.value = `完成 ${(blob.size / 1024).toFixed(0)}KB · 合成耗时 ${dt}s · 后端 ${ttsModel.value}`
    log(`三 合成成功 ${voice} -> ${(blob.size / 1024).toFixed(0)}KB WAV（${ttsModel.value}），已自动播放`, 'ok')
  } catch (e) { ttsSt.value = '失败：' + e.message; log('三 合成失败: ' + e.message, 'err') }
}

async function delVoice() {
  const voice = voiceSel.value
  if (!voice) return
  if (!confirm(`删除音色 ${voice}？`)) return
  try { await api('/tts/v1/audio/voices/' + encodeURIComponent(voice), {method: 'DELETE'})
    log('三 已删除 ' + voice, 'ok'); listVoices() }
  catch (e) { log('三 删除失败: ' + e.message, 'err') }
}

onMounted(() => { listVoices(); log('Demo 就绪：三个 Tab 对应三类接口；麦克风需在浏览器授权。') })
onBeforeUnmount(() => { if (recTimer) clearInterval(recTimer); if (recMic) recMic.stop() })
defineExpose({ listVoices })
</script>

<template>
  <section>
    <div class="card">
      <h2>接口三（A）声纹注册与音色克隆
        <span class="tag">POST /tts/v1/audio/voices</span><span class="tag">multipart</span></h2>
      <div class="desc">录制 2–15 秒参考音频（或选本地音频文件），注册后即成可复刻音色（火山 Seed-ICL 2.0）。
        注意：每账号音色配额 10 个，配额已满请先删除。</div>
      <div class="row">
        <button class="act" @click="toggleRec()">{{ recBtn }}</button>
        <span class="timer">{{ recTimerTxt }}</span>
        <span class="sub">{{ recInfo }}</span>
        <label class="act ghost" style="display:inline-block">或选择文件
          <input type="file" accept="audio/*" style="display:none" ref="refFileInput" @change="onRefFileInput"></label>
      </div>
      <WaveCanvas :chunks="chunks" />
      <div class="row">
        <input type="text" v-model="voiceName" placeholder="音色名（英文/数字/下划线）" style="width:240px">
        <button class="act" :disabled="cloneBusy" @click="cloneVoice()">注册复刻音色</button>
        <span class="sub">{{ cloneSt }}</span>
      </div>
      <div class="meta">{{ cloneResult }}</div>
    </div>
    <div class="card">
      <h2>接口三（B）克隆合成 <span class="tag">POST /tts/v1/audio/speech</span></h2>
      <div class="row">
        <select v-model="voiceSel" style="width:260px">
          <option value="" disabled>— 点击刷新音色列表 —</option>
          <option v-for="v in voices" :key="v" :value="v">{{ v }}</option>
        </select>
        <select v-model="ttsModel" style="width:170px" title="合成后端">
          <option value="qwen-tts-1.7b">本地 Qwen3-TTS-1.7B</option>
          <option value="seed-iclv2">火山 seed-iclv2</option>
        </select>
        <button class="mini" @click="listVoices()">刷新</button>
        <button class="mini" @click="delVoice()">删除选中</button>
      </div>
      <textarea v-model="ttsText" placeholder="输入要合成的文本…"></textarea>
      <div class="row">
        <button class="act" @click="speak()">合成并播放</button>
        <span class="sub">{{ ttsSt }}</span>
      </div>
      <audio ref="player" controls></audio>
      <div class="meta">{{ voicesNote }}</div>
    </div>
  </section>
</template>
