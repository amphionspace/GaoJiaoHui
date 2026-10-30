<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { store, dlog } from '../core/store.js'
import { toggleLocale } from '../core/i18n.js'
import { endingIntent, createJourneyJournal, composeJourneyJournal, illustrateJourneyJournal } from '../core/journey.js'
import { JourneyRecorder, JourneySound, JourneyVoice, cleanJourneyVoices, voiceFailureMessage, prefetchAsrSession } from '../core/journeyAudio.js'
import { warmSpeechDetector, releasePreparedDetector } from '../core/journeySpeech.js'
import JourneyIcon from './JourneyIcon.vue'
import JourneyReceipt from './JourneyReceipt.vue'
import JourneyOrb from './JourneyOrb.vue'
import JourneyStory from './JourneyStory.vue'
import JourneyMeteor from './JourneyMeteor.vue'
import './journey.css'
import './journey-editorial.css'
import './journey-2036.css'
import './journey-light.css'

const props = defineProps({ active: { type: Boolean, default: true } })
const emit = defineEmits(['settings'])
const stage = ref('welcome'), topicId = ref('future'), text = ref(''), journal = ref(null)
const recording = ref(false), connecting = ref(false), level = ref(0), paused = ref(false), audioCaptured = ref(false)
const connectionPhase = ref('microphone')
const connectionLabel = computed(() => ({ microphone: '正在开启麦克风', speech: '正在准备倾听', connection: '正在接通语音服务' }[connectionPhase.value] || '正在接通'))
const connectionHint = computed(() => ({ microphone: '如浏览器询问权限，请选择允许使用麦克风。', speech: '首次使用需要加载片刻，准备好后会提醒你开始。', connection: '麦克风已就绪，正在等待语音服务。' }[connectionPhase.value] || ''))
const error = ref(''), notice = ref(''), voiceIssue = ref('')
const imageIssue = ref(''), imageBusy = ref(false), notePending = ref(false)
const transcriptWarning = ref('')
const autoFinishSeconds = ref(0)
const voiceEnabled = ref(false), voiceState = ref('waiting'), audioUrl = ref('')
const playing = ref(false), audioPaused = ref(false), textMode = ref(false)
const printReturned = ref(false), busyLabel = ref('正在整理你的讲述')
const onHome = computed(() => stage.value === 'welcome')
const introPlaying = ref(false), introChapter = ref(0)
const storyFrameDelay = 4200
const guideReplay = ref(0)
const guideSkipped = ref(false)
const callState = computed(() => {
  if (error.value) return 'error'
  if (stage.value === 'generating') return 'processing'
  if (playing.value && !audioPaused.value) return 'speaking'
  if (connecting.value) return 'connecting'
  if (textMode.value) return 'typing'
  return recording.value ? 'listening' : 'paused'
})
const callLabel = computed(() => ({ error: '连接遇到一点问题', processing: busyLabel.value, speaking: '正在播放回信', connecting: connectionLabel.value, typing: '把想法写下来', listening: paused.value ? '我在听，慢慢说' : '正在倾听', paused: '麦克风已暂停' }[callState.value]))
const latestLine = computed(() => text.value.trim().match(/[^。！？!?\n]+[。！？!?]?/g)?.slice(-1)[0] || '')
const transcriptViewport = ref(null), followTranscript = ref(true)
const generationSeconds = ref(0)
let generationTimer

function trackTranscriptScroll() {
  const view = transcriptViewport.value
  if (view) followTranscript.value = view.scrollHeight - view.scrollTop - view.clientHeight < 48
}
async function showLatestTranscript() {
  followTranscript.value = true
  await nextTick()
  const view = transcriptViewport.value
  if (view) view.scrollTop = view.scrollHeight
}
watch(text, async () => {
  if (!followTranscript.value) return
  await nextTick()
  const view = transcriptViewport.value
  if (view) view.scrollTop = view.scrollHeight
})
watch(transcriptViewport, view => {
  if (view && followTranscript.value) view.scrollTop = view.scrollHeight
}, { flush: 'post' })
watch(stage, value => {
  clearInterval(generationTimer)
  if (value === 'generating') {
    generationSeconds.value = 0
    generationTimer = setInterval(() => { generationSeconds.value++ }, 1000)
  }
})

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
  notePending.value = false
  if (textRequest && journal.value?.summary && !journal.value.sketch) imageIssue.value = '插画生成已中断，文字手记已保留。请点击重试插画。'
  textRequest?.abort(); textRequest = null
  imageBusy.value = false
  voice?.dispose(); voice = null; candidate = null; finishing = false; lastVoiceError = ''
}
function reset() {
  cancelSession(); stage.value = 'welcome'; topicId.value = 'future'; text.value = ''; journal.value = null
  error.value = notice.value = voiceIssue.value = imageIssue.value = ''; imageBusy.value = false
  transcriptWarning.value = ''
  followTranscript.value = true
  voiceState.value = 'waiting'; paused.value = textMode.value = printReturned.value = false
}
async function beginJourney() {
  if (!props.active || recording.value || connecting.value || textMode.value) return
  stopPlayback(); unlockAudio(); error.value = ''; notice.value = ''
  const id = session, run = ++introRun
  stage.value = 'intro'; introPlaying.value = true; guideSkipped.value = false; guideReplay.value++
  warmSpeechDetector().catch(() => {})
  prefetchAsrSession()          // mint the temporary ASR credential while the story plays
  try {
    // Keep the story page quiet for now; the three visual comparisons carry the introduction.
    for (let chapter = 0; chapter < 3; chapter++) {
      introChapter.value = chapter
      await new Promise(resolve => setTimeout(resolve, storyFrameDelay))
      if (id !== session || run !== introRun || !props.active) return
    }
    introPlaying.value = false
    prefetchAsrSession()        // refresh it now that the visitor is about to speak
    // Keep the complete comparison visible until the visitor chooses to speak.
  } catch {
    if (id !== session || run !== introRun) return
    introPlaying.value = false
    error.value = '接通引导暂时没有播放成功。可以重新听，或直接开始讲述。'
  }
}
function skipGuide() {
  introRun++
  introPlaying.value = false
  guideSkipped.value = true
  prefetchAsrSession()
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
  if (!props.active || textMode.value || (!store.asrManaged && !store.apiKey.trim())) {
    if (!store.asrManaged && !store.apiKey.trim()) error.value = '语音服务还未连接，请打开设置填写网关密钥，或先用文字体验。'
    return
  }
  const id = session, myTurn = turn, prefix = text.value.trim()
  const phaseAt = { start: performance.now() }
  connecting.value = true; paused.value = false
  connectionPhase.value = 'microphone'
  transcriptWarning.value = ''
  const current = new JourneyRecorder(store.apiKey, {
    onPhase(value) {
      if (id !== session || myTurn !== turn) return
      connectionPhase.value = value
      phaseAt[value] = performance.now() - phaseAt.start
      if (value === 'ready') {
        const span = (from, to) => Math.max(0, Math.round((phaseAt[to] ?? phaseAt.ready) - (phaseAt[from] ?? 0)))
        dlog(`旅程：接通用时 · 权限 ${span('start', 'microphone')}ms · 检测 ${span('microphone', 'speech')}ms · 凭证 ${span('speech', 'connection')}ms · 连接 ${span('connection', 'ready')}ms`)
      }
    },
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
    journal.value = createJourneyJournal(fullTranscript, topicId.value, new Date(), store.locale || 'zh')
    finishing = false
    await composeNote()
  } catch (e) { if (id === session) { stopRecording(); error.value = e.message; stage.value = 'listening'; finishing = false } }
}
async function composeNote() {
  if (!journal.value) return
  stopRecording(); stopPlayback(); releaseAudio(); textRequest?.abort()
  const controller = textRequest = new AbortController(), id = session, draft = journal.value
  const revision = draft.revision
  const alive = () => id === session && textRequest === controller && journal.value?.revision === revision && !controller.signal.aborted
  stage.value = 'generating'; error.value = notice.value = imageIssue.value = ''; busyLabel.value = '正在整理你对 2036 的期待'
  notePending.value = false
  let illustrationJob = null
  const illustrate = note => illustrateJourneyJournal(note, { signal: controller.signal, apiKey: store.apiKey })
    .then(illustration => { if (alive()) journal.value = { ...journal.value, ...illustration }; return illustration })
    .catch(error => {
      if (alive()) imageIssue.value = error.name === 'TimeoutError' ? '插画生成超时，文字手记已保留。' : error.message
      return null
    })
  try {
    const result = await composeJourneyJournal(draft, {
      signal: controller.signal, apiKey: store.apiKey, language: store.locale,
      // The first pass returns a complete note; show it while the editorial pass runs.
      onDraft(partial) {
        if (!alive()) return
        journal.value = partial
        notePending.value = true
        stage.value = 'preview'
        imageBusy.value = true
        illustrationJob = illustrate(partial)
      },
      onWarning(message) { if (alive()) notice.value = message },
    })
    if (!alive()) return
    journal.value = { ...result, ...(journal.value?.sketch ? { sketch: journal.value.sketch, imageModel: journal.value.imageModel } : {}) }
    notePending.value = false
    busyLabel.value = '正在把你的想象画进手记'
    stage.value = 'preview'                 // never hold the note behind the illustration
    if (!illustrationJob) { imageBusy.value = true; illustrationJob = illustrate(result) }
    await illustrationJob
    if (!alive()) return
    imageBusy.value = false
    textRequest = null
    if (voiceEnabled.value && voice?.registration) await makeAudio(!document.hidden)
    else if (voiceEnabled.value && !textMode.value) {
      voiceState.value = 'failed'
      voiceIssue.value = '清晰人声不足5秒，本次未能创建本人音色。请重新通话，连续讲述约10秒。'
    }
  } catch (e) {
    if (id !== session || textRequest !== controller || controller.signal.aborted) return
    textRequest = null; stage.value = 'preview'
    imageBusy.value = false; notePending.value = false
    error.value = e.name === 'TimeoutError' ? '回信生成超时，完整讲述已保留，可以重新整理。' : e.message
  }
}
async function retryIllustration() {
  if (imageBusy.value || notePending.value || !journal.value?.summary) return
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
  if (!journal.value?.summary || stage.value === 'printing' || imageBusy.value || notePending.value) return
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
  // Hiding a tab must stop capture/playback, but must not cancel a paid generation.
  if (finishing) {
    // finish() has already stopped the microphone; keep its socket and turn
    // alive until the final transcript and termination have arrived.
    recording.value = connecting.value = false; level.value = 0; autoFinishSeconds.value = 0
  } else stopRecording()
  stopPlayback()
  if (stage.value === 'playback') stage.value = 'preview'
  if (!onHome.value) notice.value = finishing ? '录音已停止，正在收好最后一句话，随后继续生成手记。'
    : textRequest ? '录音已暂停，手记与插画仍在生成。' : '讲述已保留，录音与播放已暂停。'
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
  clearInterval(generationTimer)
  cancelSession(); sound?.dispose()
  window.removeEventListener('afterprint', afterPrint); window.removeEventListener('pagehide', cancelSession); document.removeEventListener('visibilitychange', pageHidden)
})
</script>

<template>
  <section class="journey journey-2036 journey-light" :class="{ 'journey-home': onHome, 'journey-story-page': stage === 'intro', 'journey-receipt-page': ['preview', 'playback', 'printing'].includes(stage) }" aria-label="和 2036 对话" @pointerdown.capture="unlockAudio" @keydown.capture="unlockAudio">
    <header class="experience-header"><span class="experience-brand"><span class="brand-dot" />和 2036 对话</span><div class="experience-header-actions"><span class="experience-step">{{ onHome ? '一段关于未来的想象' : stage === 'intro' ? '01 / 回看十年' : stage === 'listening' ? '02 / 留下期待' : '03 / 给未来的信' }}</span><button type="button" class="experience-language" :aria-label="store.locale === 'en' ? 'Switch to Chinese' : 'Switch to English'" @click="toggleLocale">{{ store.locale === 'en' ? '中' : 'EN' }}</button></div></header>
    <div v-if="error" class="journey-alert" role="alert"><span>{{ error }}</span><button v-if="!store.apiKey && !store.asrManaged" class="journey-link" @click="emit('settings')">打开设置</button><button class="journey-icon-button" aria-label="关闭提示" title="关闭提示" @click="error = ''"><JourneyIcon name="X" :size="16" /></button></div>
    <div v-if="voiceIssue && ['preview', 'playback'].includes(stage)" class="journey-alert" role="alert"><span>{{ voiceIssue }} 讲述与手记已保留。</span></div>
    <div v-if="transcriptWarning" class="journey-alert" role="alert">{{ transcriptWarning }}</div>
    <template v-if="onHome">
      <div class="journey-home-content">
        <p class="journey-eyebrow">A LITTLE CLOSER TO TOMORROW</p>
        <h1>和 2036 对话</h1>
        <p class="welcome-description">把今天的一点期待，<br />说给十年后的世界。</p>
        <JourneyOrb state="idle" />
        <p class="journey-tagline">不用想好答案，从一个小小的愿望开始。</p>
        <div class="journey-home-actions"><button class="journey-primary call-start" @click="beginJourney">开始体验<JourneyIcon name="ArrowRight" /></button></div>
        <label class="journey-consent"><input type="checkbox" v-model="voiceEnabled" />用我的声音，听见未来的回信（可选）</label>
        <p class="privacy-note">默认只转写讲述。勾选后才会尝试采集本人音色；<br />声音暂不可用时，仍可生成文字手记。</p>
      </div>
    </template>
    <div v-else-if="stage === 'intro'" class="journey-intro">
      <div class="story-heading"><p>回看过去十年</p><h2>变化，曾经也是想象。</h2></div>
      <JourneyStory :key="guideReplay" :reveal-all="guideSkipped" @skip="skipGuide" @start="startListening" @text="useText" @replay="beginJourney" />

    </div>
    <div v-else-if="['listening', 'generating'].includes(stage)" class="call-room" :data-state="callState" :aria-busy="connecting || stage === 'generating'">
      <div class="call-question" :inert="connecting"><p class="question-kicker">留一点想象给未来</p><h2>十年后的世界，<br />你希望怎样生活？</h2><p>可以是一件小事，也可以是一个大胆的念头。</p></div>
      <div class="call-presence" :inert="connecting">
        <div v-if="stage === 'generating'" class="generation-delivery"><JourneyMeteor /><p>一封穿越时空的信，正在飞向 2036</p></div>
        <JourneyOrb v-else :state="callState" :level="level" />
        <p class="call-status" role="status"><span />{{ callLabel }}</p>
        <p class="call-hint">{{ connecting ? connectionHint : stage === 'generating' ? (generationSeconds >= 25 ? '还在认真整理，完整讲述已保留，请稍候。' : '你的讲述已收到，整理好后会呈现给你。') : textMode ? '随时可以改回语音，已写下的内容会保留。' : recording ? '说完后点下方按钮，或说“我说完了”。' : '你可以重新连接，也可以用文字继续。' }}</p>
      </div>
      <div class="call-content" :inert="connecting">
        <label v-if="textMode && stage === 'listening'" class="call-text"><span>你的期待</span><textarea v-model="text" placeholder="2036 年，我希望……" rows="4" /></label>
        <div v-else class="call-caption call-transcript">
          <div class="transcript-heading"><span>你的完整讲述</span><small>可向上滚动查看</small></div>
          <div ref="transcriptViewport" class="transcript-viewport" role="log" aria-label="完整讲述记录" aria-live="polite" aria-atomic="false" tabindex="0" @scroll="trackTranscriptScroll"><p>{{ text || (audioCaptured ? '已收到声音，正在识别…' : '第一句话，会从这里开始。') }}</p></div>
          <button v-if="!followTranscript" class="transcript-latest journey-link" @click="showLatestTranscript"><JourneyIcon name="ChevronDown" :size="16" />回到最新一句</button>
        </div>
        <div v-if="journal?.messageToSelf && stage === 'generating'" class="call-pending-reply"><span>给你的回信</span><p>{{ journal.messageToSelf }}</p></div>
      </div>
      <footer class="call-dock" :inert="connecting">
        <p class="dock-note" role="status">{{ notice || (autoFinishSeconds ? `${autoFinishSeconds} 秒后开始整理，继续说话可接着记录。` : stage === 'generating' ? '正在处理 · 麦克风已关闭' : '只记录你此刻想留下的话') }}</p>
        <div class="call-main-actions"><button v-if="stage === 'listening'" class="journey-primary" @click="finishStory" :disabled="connecting || (!text.trim() && !audioCaptured)"><JourneyIcon name="Check" />我说完了</button><button v-else class="journey-primary" disabled>正在整理…</button><button v-if="stage === 'listening' && !recording && !connecting && !textMode" class="journey-secondary" @click="listen"><JourneyIcon name="Mic" />重新连接</button></div>
        <div class="call-other-actions"><button v-if="stage === 'listening'" class="journey-link" @click="textMode ? (textMode = false, listen()) : useText()"><JourneyIcon :name="textMode ? 'Mic' : 'Pencil'" :size="17" />{{ textMode ? '改用语音' : '文字输入' }}</button><button v-if="stage === 'generating' && journal?.messageToSelf && !textRequest" class="journey-link" @click="skipAudio">先看手记</button><button class="journey-link" @click="reset"><JourneyIcon name="X" :size="17" />结束对话</button></div>
      </footer>
      <div v-if="connecting" class="mic-connection-overlay">
        <div class="mic-connection-card" role="status" aria-live="polite">
          <div class="mic-connection-pill"><i class="connection-spinner" />{{ connectionLabel }}</div>
          <p>{{ connectionHint }}</p><small>连接完成后，就可以开始说话。</small>
          <div class="mic-connection-actions"><button class="journey-secondary" @click="useText">改用文字</button><button class="journey-link" @click="reset">返回首页</button></div>
        </div>
      </div>
    </div>
    <div v-else-if="['preview', 'playback', 'printing'].includes(stage) && journal" class="journey-result">
      <div v-if="journal.messageToSelf" class="reply-card"><span>{{ playing && !audioPaused ? '正在播放回信' : '来自未来的一句话' }}</span><p>{{ journal.messageToSelf }}</p></div>
      <div v-if="journal.summary" class="journey-paper-preview"><JourneyReceipt :journal="journal" :image-error="imageIssue" :image-busy="imageBusy" @retry-image="retryIllustration" /></div>
      <div v-else class="journey-recovery"><h2>讲述已保留</h2><p>回信还没准备好，你可以直接重试。</p><div class="recovery-transcript" tabindex="0" aria-label="已保留的完整讲述">{{ journal.originalText }}</div></div>
      <div class="journey-result-content">
        <p v-if="imageIssue" class="journey-notice" role="status">{{ imageIssue }} <button class="journey-link" @click="retryIllustration">重试插画</button></p>
        <p v-if="notePending" class="journey-notice" role="status">正在最后核对措辞，文字已经可以阅读…</p>
        <p v-if="imageBusy" class="journey-notice" role="status">正在画下你的期待…</p>
        <button v-if="!journal.messageToSelf" class="journey-primary retry-note" @click="composeNote"><JourneyIcon name="RotateCcw" />重新整理</button>
        <template v-if="stage === 'printing'"><p class="journey-notice">{{ printReturned ? '打印窗口已关闭，请确认是否收到手记。' : '等待打印操作完成。' }}</p><div class="journey-actions"><button class="journey-primary" @click="complete"><JourneyIcon name="Check" />已收到手记</button><button class="journey-secondary" @click="backToPreview">返回预览</button></div></template>
        <template v-else>
          <div class="journey-actions"><button v-if="journal.summary" class="journey-primary" :disabled="imageBusy || notePending" @click="printJournal"><JourneyIcon name="Printer" />打印手记</button><button v-if="audioUrl" class="journey-play" :aria-label="playing && !audioPaused ? '暂停播放' : '播放我的声音'" :title="playing && !audioPaused ? '暂停播放' : '播放我的声音'" @click="togglePlayback"><JourneyIcon :name="playing && !audioPaused ? 'Pause' : 'Play'" /></button><button v-else-if="journal.messageToSelf && voiceEnabled && voiceState === 'failed'" class="journey-secondary" @click="makeAudio(true, true)"><JourneyIcon name="Volume2" />重试声音</button></div>
        </template>
        <button class="journey-secondary result-home" @click="reset"><JourneyIcon name="ArrowLeft" />返回首页</button>
      </div>
    </div>
    <div v-else-if="stage === 'done'" class="journey-done"><JourneyIcon name="Sprout" :size="42" /><h2>这一刻，留住了。</h2><p>带上这份回信，慢慢走向你的未来。</p><button class="journey-primary" @click="reset"><JourneyIcon name="ArrowLeft" />返回首页</button></div>
    <Teleport to="body"><div v-if="journal && active" id="journey-print-root"><JourneyReceipt :journal="journal" /></div></Teleport>
  </section>
</template>
