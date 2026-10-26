<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { store } from '../core/store.js'
import { endingIntent, createJourneyJournal, composeJourneyJournal, illustrateJourneyJournal } from '../core/journey.js'
import { JourneyRecorder, JourneySound, JourneyVoice, cleanJourneyVoices, voiceFailureMessage } from '../core/journeyAudio.js'
import { warmSpeechDetector, releasePreparedDetector } from '../core/journeySpeech.js'
import JourneyIcon from './JourneyIcon.vue'
import JourneyReceipt from './JourneyReceipt.vue'
import JourneyCollage from './JourneyCollage.vue'
import JourneyStory from './JourneyStory.vue'
import JourneyMeteor from './JourneyMeteor.vue'
import './journey.css'
import './journey-editorial.css'
import './journey-2036.css'

const props = defineProps({ active: { type: Boolean, default: true } })
const emit = defineEmits(['settings'])
const stage = ref('welcome'), topicId = ref('future'), text = ref(''), journal = ref(null)
const recording = ref(false), connecting = ref(false), level = ref(0), paused = ref(false), audioCaptured = ref(false)
const connectionPhase = ref('microphone')
const connectionLabel = computed(() => ({ microphone: '正在开启麦克风', speech: '正在准备倾听', connection: '正在接通语音服务' }[connectionPhase.value] || '正在接通'))
const connectionHint = computed(() => ({ microphone: '如浏览器询问权限，请选择允许使用麦克风。', speech: '首次使用需要加载片刻，准备好后会提醒你开始。', connection: '麦克风已就绪，正在等待语音服务。' }[connectionPhase.value] || ''))
const error = ref(''), notice = ref(''), voiceIssue = ref('')
const imageIssue = ref(''), imageBusy = ref(false)
const transcriptWarning = ref('')
const autoFinishSeconds = ref(0)
const voiceEnabled = ref(true), voiceState = ref('waiting'), audioUrl = ref('')
const playing = ref(false), audioPaused = ref(false), textMode = ref(false)
const printReturned = ref(false), busyLabel = ref('正在整理你的讲述')
const onHome = computed(() => stage.value === 'welcome')
const introPlaying = ref(false), introChapter = ref(0)
let recorder = null, sound = null, voice = null, candidate = null, textRequest = null
let session = 0, audioTask = 0, turn = 0, finishing = false, introRun = 0
let doneTimer, maxTimer
let lastVoiceError = ''

function unlockAudio() { sound?.unlock() }
function clearTimers() { for (const timer of [doneTimer, maxTimer]) clearTimeout(timer) }
function stopRecording() {
  turn++; clearTimers(); recorder?.stop(); recorder = null
  recording.value = connecting.value = false; level.value = 0; audioCaptured.value = false
  autoFinishSeconds.value = 0
}
function stopPlayback() {
  audioTask++; sound?.stop(); playing.value = audioPaused.value = false
}
function releaseAudio() { if (audioUrl.value) URL.revokeObjectURL(audioUrl.value); audioUrl.value = '' }
function cancelSession() {
  releasePreparedDetector()
  introRun++; introPlaying.value = false
  session++; stopRecording(); stopPlayback(); releaseAudio()
  textRequest?.abort(); textRequest = null
  imageBusy.value = false
  voice?.dispose(); voice = null; candidate = null; finishing = false; lastVoiceError = ''
}
function reset() {
  cancelSession(); stage.value = 'welcome'; topicId.value = 'future'; text.value = ''; journal.value = null
  error.value = notice.value = voiceIssue.value = imageIssue.value = ''; imageBusy.value = false
  transcriptWarning.value = ''
  voiceState.value = 'waiting'; paused.value = textMode.value = printReturned.value = false
}
async function beginJourney() {
  if (!props.active || recording.value || connecting.value || textMode.value || introPlaying.value) return
  stopPlayback(); unlockAudio(); error.value = ''; notice.value = ''
  const id = session, run = ++introRun
  stage.value = 'intro'; introPlaying.value = true
  warmSpeechDetector().catch(() => {})
  try {
    for (let chapter = 0; chapter < 4; chapter++) {
      introChapter.value = chapter
      const ended = await sound.play(`/journey/story-2036-${chapter}.wav`)
      if (id !== session || run !== introRun || !props.active) return
      if (!ended) { introPlaying.value = false; return }
    }
    introPlaying.value = false
    await startListening()
  } catch {
    if (id !== session || run !== introRun) return
    introPlaying.value = false
    error.value = '接通引导暂时没有播放成功。可以重新听，或直接开始讲述。'
  }
}
async function startListening() {
  if (!props.active || stage.value !== 'intro') return
  introRun++; introPlaying.value = false; stopPlayback()
  stage.value = 'listening'; error.value = ''
  await listen()
}
async function listen() {
  unlockAudio()
  stopRecording()
  if (stage.value !== 'listening') return
  if (!props.active || textMode.value || !store.apiKey.trim()) {
    if (!store.apiKey.trim()) error.value = '语音服务还未连接，请打开设置填写网关密钥，或先用文字体验。'
    return
  }
  const id = session, myTurn = turn, prefix = text.value.trim()
  connecting.value = true; paused.value = false
  connectionPhase.value = 'microphone'
  transcriptWarning.value = ''
  const current = new JourneyRecorder(store.apiKey, {
    onPhase(value) { if (id === session && myTurn === turn) connectionPhase.value = value },
    onText(value) {
      if (id !== session || myTurn !== turn) return
      text.value = [prefix, value].filter(Boolean).join('\n')
      clearTimeout(doneTimer)
      if (endingIntent(value)) doneTimer = setTimeout(() => { if (id === session && !finishing) finishStory() }, 650)
    },
    onLevel(value, speaking) {
      if (id !== session || myTurn !== turn) return
      level.value = value
      if (speaking) { paused.value = false; autoFinishSeconds.value = 0 }
    },
    onActivity(silence, heardSpeech) {
      if (id !== session || myTurn !== turn || finishing) return
      paused.value = heardSpeech && silence >= 3.5
      autoFinishSeconds.value = heardSpeech && text.value.trim() && silence >= 5 ? Math.max(0, Math.ceil(8 - silence)) : 0
      if (heardSpeech && silence >= 8 && text.value.trim()) finishStory()
    },
    onAudio() { if (id === session && myTurn === turn) audioCaptured.value = true },
    onError(message) { if (id === session && myTurn === turn) { error.value = message; stopRecording() } },
    onWarning(message) { if (id === session) transcriptWarning.value = message },
    ...(voiceEnabled.value ? { onSample(blob) { if (id === session) prepareVoice(blob) } } : {}),
  }, { context: sound?.context })
  recorder = current
  try {
    await current.start()
    if (id !== session || myTurn !== turn || !props.active) { current.stop(); return }
    recording.value = true; connecting.value = false; error.value = ''
    maxTimer = setTimeout(() => {
      if (text.value.trim()) finishStory()
      else { stopRecording(); error.value = '暂时没有听清讲述，请靠近麦克风重试，或用文字记录。' }
    }, 180000)
  } catch (e) { if (id === session && myTurn === turn) { stopRecording(); error.value = e.message } }
}
function useText() { releasePreparedDetector(); introRun++; introPlaying.value = false; stopPlayback(); sound?.unlock?.(); stopRecording(); textMode.value = true; error.value = ''; transcriptWarning.value = ''; stage.value = 'listening' }
function prepareVoice(blob) {
  if (!voiceEnabled.value || (voice?.registration && voiceState.value !== 'failed')) return
  voice?.dispose()
  candidate = blob; lastVoiceError = ''; voiceIssue.value = ''
  const id = session
  const current = voice = new JourneyVoice(store.apiKey)
  voiceState.value = 'registering'
  return current.register(blob)
    .then(() => { if (id === session && voice === current) voiceState.value = 'ready' })
    .catch(e => { if (id === session && voice === current) { lastVoiceError = e.message; voiceState.value = 'failed'; voiceIssue.value = voiceFailureMessage(e) } })
}
async function finishStory() {
  if (finishing || stage.value !== 'listening') return
  sound?.unlock?.()
  finishing = true; stage.value = 'generating'; busyLabel.value = '正在收好你的最后一句话'
  const id = session, current = recorder
  clearTimers()
  try {
    if (current) await current.finish()
    if (id !== session) return
    stopRecording()
    const fullTranscript = text.value
    const content = (endingIntent(fullTranscript)?.text ?? fullTranscript).trim()
    if (!content) throw new Error('暂时没有识别到文字。可以重试录音，或改用文字留下这段讲述。')
    text.value = content
    journal.value = createJourneyJournal(fullTranscript, topicId.value)
    finishing = false
    await composeNote()
  } catch (e) { if (id === session) { stopRecording(); error.value = e.message; stage.value = 'listening'; finishing = false } }
}
async function composeNote() {
  if (!journal.value) return
  stopRecording(); stopPlayback(); releaseAudio(); textRequest?.abort()
  const controller = textRequest = new AbortController(), id = session, draft = journal.value
  stage.value = 'generating'; error.value = notice.value = imageIssue.value = ''; busyLabel.value = '正在整理你对 2036 的期待'
  try {
    const result = await composeJourneyJournal(draft, { signal: controller.signal, apiKey: store.apiKey })
    if (id !== session || textRequest !== controller || journal.value?.revision !== draft.revision) return
    journal.value = result
    busyLabel.value = '正在把你的想象画进手记'
    try {
      const illustration = await illustrateJourneyJournal(result, { signal: controller.signal, apiKey: store.apiKey })
      if (id !== session || textRequest !== controller || controller.signal.aborted) return
      journal.value = { ...result, ...illustration }
    } catch (e) {
      if (id !== session || textRequest !== controller || controller.signal.aborted) return
      imageIssue.value = e.name === 'TimeoutError' ? '插画生成超时，文字手记已保留。' : e.message
    }
    textRequest = null; stage.value = 'preview'
    if (voiceEnabled.value && voice?.registration) await makeAudio(true)
  } catch (e) {
    if (id !== session || textRequest !== controller || controller.signal.aborted) return
    textRequest = null; stage.value = 'preview'
    error.value = e.name === 'TimeoutError' ? '回信生成超时，完整讲述已保留，可以重新整理。' : e.message
  }
}
async function retryIllustration() {
  if (imageBusy.value || !journal.value?.summary) return
  const controller = textRequest = new AbortController(), id = session, draft = journal.value
  imageBusy.value = true; imageIssue.value = ''
  try {
    const illustration = await illustrateJourneyJournal(draft, { signal: controller.signal, apiKey: store.apiKey })
    if (id === session && textRequest === controller && !controller.signal.aborted) journal.value = { ...journal.value, ...illustration }
  } catch (e) {
    if (id === session && textRequest === controller && !controller.signal.aborted) imageIssue.value = e.message
  } finally {
    if (textRequest === controller) { textRequest = null; imageBusy.value = false }
  }
}
async function makeAudio(autoplay = false, retry = false) {
  if (!journal.value?.messageToSelf || !voiceEnabled.value) return
  stopRecording(); stopPlayback(); releaseAudio()
  const id = session, job = ++audioTask, revision = journal.value.revision
  error.value = voiceIssue.value = ''; stage.value = 'generating'; busyLabel.value = '正在用你的声音，接通这封来自未来的回信'
  try {
    if (retry && voiceState.value === 'failed' && !voice?.ready && candidate) {
      await voice?.dispose()
      if (id !== session || job !== audioTask) return
      voice = null; prepareVoice(candidate)
    }
    if (!voice) throw new Error(lastVoiceError || '清晰录音不足，请重新开始通话后再试。')
    const blob = await voice.synthesize(journal.value.messageToSelf)
    if (id !== session || job !== audioTask || journal.value?.revision !== revision) return
    audioUrl.value = URL.createObjectURL(blob); voiceState.value = 'ready'; stage.value = 'preview'; notice.value = ''
    if (autoplay) await replay()
  } catch (e) {
    if (id !== session || job !== audioTask) return
    stage.value = 'preview'; voiceState.value = 'failed'
    lastVoiceError = e.message
    voiceIssue.value = voiceFailureMessage(e)
  }
}
function skipAudio() { stopPlayback(); stage.value = 'preview'; notice.value = '手记已经准备好，声音可以稍后重试。' }
async function replay() {
  unlockAudio()
  if (!audioUrl.value) { await makeAudio(true); return }
  stopRecording(); stopPlayback()
  const id = session, job = audioTask
  stage.value = 'playback'; playing.value = true; audioPaused.value = false
  try {
    await sound.play(audioUrl.value)
    if (id !== session || job !== audioTask) return
    playing.value = false; stage.value = 'preview'
  } catch (e) {
    if (id !== session || job !== audioTask) return
    playing.value = false; stage.value = 'preview'
    error.value = e.name === 'NotAllowedError' ? '声音已经生成，浏览器需要一次点击才能开启播放。' : `声音已生成，但播放失败：${e.message || '请重试'}。`
  }
}
async function togglePlayback() {
  if (!playing.value) { await replay(); return }
  if (!audioPaused.value) { sound.pause(); audioPaused.value = true }
  else { try { await sound.resume(); audioPaused.value = false } catch { error.value = '播放未能继续，请重新播放。' } }
}
async function printJournal() {
  if (!journal.value || stage.value === 'printing' || imageBusy.value) return
  const id = session
  stopPlayback(); stopRecording(); stage.value = 'printing'; printReturned.value = false
  await nextTick()
  try {
    for (const img of document.querySelectorAll?.('#journey-print-root img') || []) await img.decode()
  } catch { error.value = '插画尚未加载完成，请重试打印。'; stage.value = 'preview'; return }
  if (id === session && stage.value === 'printing') window.print()
}
function afterPrint() { if (stage.value === 'printing') printReturned.value = true }
function backToPreview() { stage.value = 'preview' }
function complete() { cancelSession(); stage.value = 'done'; error.value = notice.value = '' }
watch(() => props.active, active => {
  if (!active) {
    cancelSession()
    if (['intro', 'generating', 'playback', 'printing'].includes(stage.value)) stage.value = journal.value ? 'preview' : 'listening'
    if (journal.value) notice.value = '手记已保留。离开页面后录音与播放已停止。'
  }
})
watch(voiceEnabled, enabled => {
  if (!enabled) {
    stopPlayback(); voice?.dispose(); voice = null; candidate = null; releaseAudio(); voiceState.value = 'waiting'; voiceIssue.value = ''
    if (journal.value && !textRequest && ['generating', 'playback'].includes(stage.value)) stage.value = 'preview'
  }
})
function pageHidden() {
  if (!document.hidden) return
  cancelSession()
  if (['intro', 'generating', 'playback', 'printing'].includes(stage.value)) stage.value = journal.value ? 'preview' : 'listening'
  if (!onHome.value) notice.value = '讲述已保留，录音与播放已暂停。'
}
onMounted(() => {
  sound = new JourneySound()
  window.addEventListener('afterprint', afterPrint); window.addEventListener('pagehide', cancelSession); document.addEventListener('visibilitychange', pageHidden)
  cleanJourneyVoices(store.apiKey)
})
watch(() => store.apiKey, () => {
  cancelSession()
  if (journal.value) { stage.value = 'preview'; notice.value = '连接设置已更新，讲述与手记已保留。' }
  else if (!onHome.value) stage.value = 'listening'
})
onBeforeUnmount(() => {
  cancelSession(); sound?.dispose()
  window.removeEventListener('afterprint', afterPrint); window.removeEventListener('pagehide', cancelSession); document.removeEventListener('visibilitychange', pageHidden)
})
</script>

<template>
  <section class="journey journey-2036" :class="{ 'journey-home': onHome, 'journey-story-page': stage === 'intro', 'journey-receipt-page': ['preview', 'playback', 'printing'].includes(stage) }" aria-label="和 2036 对话" @pointerdown.capture="unlockAudio" @keydown.capture="unlockAudio">
    <div class="journey-windowbar" aria-hidden="true"><span class="journey-window-dots"><i /><i /><i /></span><span>future.call / to myself</span><span class="journey-window-mark">↗</span></div>
    <div v-if="onHome" class="journey-topline"><span>高交会 · 安菲翁科技</span><span>2026 → 2036</span></div>
    <div v-if="!onHome" class="journey-brand"><span v-if="stage !== 'intro'">和 2036 对话</span><button class="journey-icon-button" title="结束通话" aria-label="结束通话" @click="reset"><JourneyIcon name="X" /></button></div>
    <div v-if="error" class="journey-alert" role="alert"><span>{{ error }}</span><button v-if="!store.apiKey" class="journey-link" @click="emit('settings')">打开设置</button><button class="journey-icon-button" aria-label="关闭提示" title="关闭提示" @click="error = ''"><JourneyIcon name="X" :size="16" /></button></div>
    <div v-if="voiceIssue && ['preview', 'playback'].includes(stage)" class="journey-alert" role="alert"><span>{{ voiceIssue }} 讲述与手记已保留。</span></div>
    <div v-if="transcriptWarning" class="journey-alert" role="alert">{{ transcriptWarning }}</div>
    <template v-if="onHome">
      <div class="journey-home-content">
        <p class="journey-eyebrow" lang="en">Hello, 2036.</p>
        <h1><span>和 <b>2036</b></span><span>对话</span></h1>
        <JourneyCollage />
        <p class="journey-tagline">十年后的世界，你想怎样生活？</p>
        <div class="journey-home-actions"><button class="journey-primary call-start" @click="beginJourney"><JourneyIcon name="Phone" />开始通话<JourneyIcon name="ArrowRight" /></button></div>
        <label class="journey-consent"><input type="checkbox" v-model="voiceEnabled" />用我的声音，听见未来的回信</label>
      </div>
    </template>
    <div v-else-if="stage === 'intro'" class="journey-intro">
      <JourneyStory :chapter="introChapter" />
      <p class="story-caption">对 2036 的期待</p>
      <div class="story-controls"><button v-if="!introPlaying" class="journey-icon-button" title="重新播放故事" aria-label="重新播放故事" @click="beginJourney"><JourneyIcon name="RotateCcw" /></button><button class="journey-icon-button" title="跳过故事，开始讲述" aria-label="跳过故事，开始讲述" @click="startListening"><JourneyIcon name="Mic" /></button><button class="journey-icon-button" title="用文字留下期待" aria-label="用文字留下期待" @click="useText"><JourneyIcon name="Pencil" /></button></div>
    </div>
    <div v-else-if="stage === 'listening'" class="journey-listening">
      <p class="story-caption">对 2036 的期待</p><p class="journey-section-label" role="status"><span :class="['status-dot', { live: recording }]" />{{ textMode ? '写下你的期待' : connecting ? connectionLabel : recording ? paused ? '正在等待下一句话' : '可以开始说话了' : '讲述已暂停' }}</p><p v-if="connecting" class="journey-subtitle">{{ connectionHint }}</p>
      <div v-if="!textMode" class="journey-wave large" aria-hidden="true"><i v-for="i in 23" :key="i" :style="{ height: `${6 + level * 50 * (.3 + Math.abs(Math.sin(i)) * .7)}px` }" /></div>
      <label v-if="textMode" class="journey-text-entry"><span>你的讲述</span><textarea v-model="text" placeholder="2036 年，我希望……" rows="7" /></label>
      <div v-else class="journey-transcript" role="log" aria-label="实时讲述" aria-live="polite"><span class="journey-section-label">{{ connecting ? '正在连接' : text ? '你的完整讲述' : audioCaptured ? '已收到声音，正在识别' : recording ? '等待你的声音' : '讲述已暂停' }}</span><p>{{ text || '你的第一句话，会出现在这里。' }}</p></div>
      <p class="journey-notice" v-if="notice">{{ notice }}</p><div class="journey-actions"><button class="journey-primary" @click="finishStory" :disabled="!text.trim() && !audioCaptured"><JourneyIcon name="Check" />我说完了</button><button v-if="!recording && !connecting && !textMode" class="journey-secondary" @click="listen"><JourneyIcon name="Mic" />继续录音</button><button class="journey-link" @click="textMode ? (textMode = false, listen()) : useText()">{{ textMode ? '改用语音' : '改用文字' }}</button></div>
      <p class="journey-small" role="status">{{ textMode ? '写完后，把今天留在手记里。' : autoFinishSeconds ? `${autoFinishSeconds} 秒后开始整理，继续说话可接着记录。` : paused ? '还想说些什么，我在听。' : '' }}</p><button class="journey-link muted" @click="reset"><JourneyIcon name="ArrowLeft" :size="15" />结束这次通话</button>
    </div>
    <div v-else-if="stage === 'generating'" class="journey-generating" aria-busy="true"><JourneyMeteor /><p class="journey-meteor-caption" role="status" :aria-label="`一封穿越时空的信，正在飞向 2036。${busyLabel}`">一封穿越时空的信，正在飞向 2036</p><button v-if="journal?.messageToSelf && !textRequest" class="journey-secondary" @click="skipAudio">先看手记<JourneyIcon name="ArrowRight" /></button><button class="journey-link muted" @click="reset">重新开始</button></div>
    <div v-else-if="['preview', 'playback', 'printing'].includes(stage) && journal" class="journey-result">
      <div class="journey-paper-preview"><JourneyReceipt :journal="journal" /></div>
      <div class="journey-result-content">
        <p v-if="imageIssue" class="journey-notice" role="status">{{ imageIssue }} <button class="journey-link" @click="retryIllustration">重试插画</button></p>
        <p v-if="imageBusy" class="journey-notice" role="status">正在画下你的期待…</p>
        <button v-if="!journal.messageToSelf" class="journey-secondary" @click="composeNote"><JourneyIcon name="RotateCcw" />重新整理</button>
        <template v-if="stage === 'printing'"><p class="journey-notice">{{ printReturned ? '打印窗口已关闭，请确认是否收到手记。' : '等待打印操作完成。' }}</p><div class="journey-actions"><button class="journey-primary" @click="complete"><JourneyIcon name="Check" />已收到手记</button><button class="journey-secondary" @click="backToPreview">返回预览</button></div></template>
        <template v-else>
          <div class="journey-actions"><button class="journey-primary" :disabled="imageBusy" @click="printJournal"><JourneyIcon name="Printer" />打印手记</button><button v-if="audioUrl" class="journey-play" :aria-label="playing && !audioPaused ? '暂停播放' : '播放我的声音'" :title="playing && !audioPaused ? '暂停播放' : '播放我的声音'" @click="togglePlayback"><JourneyIcon :name="playing && !audioPaused ? 'Pause' : 'Play'" /></button><button v-else-if="journal.messageToSelf && voiceEnabled && voiceState === 'failed'" class="journey-secondary" @click="makeAudio(true, true)"><JourneyIcon name="Volume2" />重试声音</button></div>
        </template>
      </div>
    </div>
    <div v-else-if="stage === 'done'" class="journey-done"><JourneyIcon name="Sprout" :size="42" /><h2>这一刻，留住了。</h2><p>带上这份回信，慢慢走向你的未来。</p><button class="journey-primary" @click="reset(); beginJourney()"><JourneyIcon name="Phone" />开始新的通话</button></div>
    <Teleport to="body"><div v-if="journal && active" id="journey-print-root"><JourneyReceipt :journal="journal" /></div></Teleport>
  </section>
</template>
