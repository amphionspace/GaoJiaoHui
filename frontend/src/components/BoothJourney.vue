<script setup>
/* 「未来手记」电话亭旅程 —— 8 屏状态机（对应设计稿 01–08，逻辑/文案完整，视觉从简）
   01 idle 获得问题 | 02 listening 自由讲述 | 03 pause 暂时停顿(不自动结束,说话自动回02)
   04 summarizing 完成讲述·整理手记 | 05 journal 生成手记 | 06 editing 语音修改(循环)
   07 confirm 确认打印 | 08 printing/done 打印完成·取走手记
   关键规则：只有「我说完了」(按钮或语音) 才结束讲述；静音只切安抚屏。 */
import { ref, computed, onBeforeUnmount } from 'vue'
import { WS_HOST, WS_HOST_LEGACY } from '../core/api.js'
import { store, log } from '../core/store.js'
import { SR, FRAME, Mic, b64frame } from '../core/audio.js'
import { buildJournal, applyEdit } from '../core/journal.js'

/* 三个问题连讲：每问独立走「讲述→修改→打印」；08 取走后倒计时自动进下一问 */
const QUESTIONS = [
  { label: '最惊喜的产品', hint: '今天最让你惊喜的产品或技术是什么？' },
  { label: '一个新想法', hint: '如果让你加一个新想法，你会加什么？' },
  { label: '今天的小故事', hint: '今天遇到的一件小事，说给未来听' },
]
const IDLE_Q = ['今天在高交会，', '有什么让你觉得', '“未来已经来了”？']

const screen = ref('idle')            // idle|listening|pause|nextq|summarizing|journal|editing|confirm|printing|done
const qIndex = ref(0)                 // 当前第几问（0..2）
const answers = ref(['', '', ''])     // 三问各自的讲述全文（讲完一问自动存入）
const nextQCountdown = ref(0)         // 「下一问」过渡屏倒计时
const transcript = ref('')            // 讲述实时记录（全量累积）
const finalText = ref('')             // 讲述最终全文
const journal = ref(null)
const changes = ref([])               // 06 屏变更标注 [{where,label}]
const editUtterance = ref('')         // 修改轮实时指令
const editApplied = ref(null)         // 最近一次应用结果文案
const editMode = ref('voice')         // voice|text
const editTextInput = ref('')
const printMsg = ref('')
const pauseSec = ref(3)               // 静音多久切「暂时停顿」安抚屏（不结束）
const micLevel = ref(0)               // 实时麦克风音量 0-1（驱动「我在听」音量条，现场排障一眼可见）
let silenceWarnT = null, silenceWarned = false

/* 底部三段旅程状态推导 */
const stages = computed(() => {
  const s = screen.value
  const tell = ['idle', 'listening', 'pause', 'nextq', 'summarizing'].includes(s)
  const tellDone = !tell
  const edit = ['journal', 'editing'].includes(s)
  const print = ['confirm', 'printing', 'done'].includes(s)
  return [
    { name: '讲述', state: tellDone ? 'checked' : 'active' },
    { name: '修改', state: tell ? 'inactive' : edit ? 'active' : 'checked' },
    { name: '打印', state: print ? (s === 'done' ? 'checked' : 'active') : 'inactive' },
  ]
})

/* ---- 讲述会话（02/03 共用一条 WS） ---- */
let ws = null, mic = null, stopFlag = false, sentFrames = 0, finishTimer = null
let vadSpeechMs = 0, vadSilenceMs = 0, vadHas = false, finished = false

function feedVad(pcm) {
  let sum = 0; for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i]
  const rms = Math.sqrt(sum / pcm.length) / 32768, durMs = pcm.length / SR * 1000
  micLevel.value = Math.min(1, rms * 8)               // 约rms0.015(触发阈值)→0.12，正常说话0.05-0.3→0.4-1
  if (rms > 0.015) {
    vadSpeechMs += durMs; vadSilenceMs = 0
    if (!vadHas && vadSpeechMs >= 400) vadHas = true
    if (vadHas && screen.value === 'pause') { screen.value = 'listening'; log('旅程：继续讲述') }
  } else if (vadHas) {
    vadSilenceMs += durMs
    if (screen.value === 'listening' && vadSilenceMs >= pauseSec.value * 1000) {
      screen.value = 'pause'
      log(`旅程：静音 ${pauseSec.value}s -> 暂时停顿屏（不会自动结束）`, 'evt')
    }
  }
}

function saidDone(text) {           // 语音结束语检测（去标点后尾部包含）
  const t = String(text || '').replace(/[，。！？,.!?~\s]/g, '')
  return /我说完了$/.test(t) || /我说完了/.test(t.slice(-12))
}

async function beginSpeak() {       // 01 -> 02：开 WS + 麦克风，一条会话贯穿 02/03
  if (ws) return
  transcript.value = ''; finalText.value = ''
  stopFlag = false; sentFrames = 0; finished = false; turnDoneHandled = false
  vadSpeechMs = 0; vadSilenceMs = 0; vadHas = false
  micLevel.value = 0; silenceWarned = false
  try {
    ws = new WebSocket(`${WS_HOST_LEGACY}/asr/v1/realtime?api_key=${encodeURIComponent(store.apiKey)}`)
    ws.onopen = () => {
      log('旅程：讲述会话 WS 已连接', 'ok')
      screen.value = 'listening'
      ws.send(JSON.stringify({type: 'session.update', session: {language: 'auto'}}))
      const sendJSON = f => { if (ws.readyState === 1) { sentFrames++
        ws.send(JSON.stringify({type: 'input_audio_buffer.append', audio: b64frame(f)})) } }
      mic = new Mic()
      mic.start(pcm => { feedVad(pcm)
        for (let i = 0; i < pcm.length; i += FRAME) sendJSON(pcm.subarray(i, i + FRAME)) })
        .catch(e => { log('旅程：麦克风失败 - ' + e.message, 'err'); abortSpeak() })
      // 静音自检：正在推流但 VAD 从未检测到声音 → 大概率输入设备选错/系统层静音（服务端会照常计费但识别为空）
      clearTimeout(silenceWarnT)
      silenceWarnT = setTimeout(() => {
        if (ws && !vadHas && !silenceWarned) {
          silenceWarned = true
          log('旅程：⚠ 麦克风一直没有声音 —— 请检查系统输入设备选择、麦克风权限或音量（上方音量条应有起伏）', 'evt')
        }
      }, 6000)
    }
    ws.onmessage = ev => {
      let d; try { d = JSON.parse(ev.data) } catch (e) { return }
      const t = d.type || ''
      if (t === 'transcription.delta') {
        if (!transcript.value && (d.text || d.delta)) log('旅程：识别通道已通，开始出字', 'ok')
        transcript.value = d.text || d.delta || ''
        if (!finished && screen.value !== 'summarizing' && saidDone(transcript.value)) {
          log('旅程：识别到结束语「我说完了」', 'evt')
          finishSpeak()
        }
      } else if (t === 'transcription.done') {
        finalText.value = d.text || transcript.value
        log('旅程：讲述全文已收到（计费 ' + (d.usage && d.usage.seconds ? d.usage.seconds.toFixed(1) + 's' : '?') + '）', 'ok')
        if (finished) turnDone()
      } else if (t === 'error') {
        log('旅程：服务端错误 - ' + (d.message || JSON.stringify(d).slice(0, 200)), 'err')
      }
    }
    ws.onclose = () => { ws = null }
    ws.onerror = () => log('旅程：WS 错误', 'err')
  } catch (e) { log('旅程：' + e.message, 'err'); abortSpeak() }
}

/* 主动关闭 WS：摘掉回调再关，避免服务端随后断开被误报成「WS 错误」 */
function closeWsQuiet(s) {
  try { s.onerror = null; s.onclose = null; s.close() } catch (e) {}
}

function finishSpeak() {            // 「我说完了」：出全文 -> 存本问 -> 自动下一问或整理
  if (finished) return
  finished = true
  if (mic) { mic.stop(); mic = null }
  const clean = t => String(t || '').replace(/我说完了[。！？.!?\s]*$/, '').trim()
  finalText.value = clean(transcript.value)
  if (ws && ws.readyState === 1) {
    if (sentFrames > 0) ws.send(JSON.stringify({type: 'input_audio_buffer.commit', final: true}))
    else closeWsQuiet(ws)
    finishTimer = setTimeout(turnDone, 3000)        // done 未回则兜底
  } else turnDone()
}

/* ---- 三问连讲：一问讲完 -> 过渡屏 3s 自动开始下一问；最后一问讲完 -> 合并整理 ---- */
let nextQT = null, turnDoneHandled = false

function turnDone() {               // 本问 done/兜底归口（防重入）
  if (turnDoneHandled) return
  turnDoneHandled = true
  clearTimeout(finishTimer); finishTimer = null
  clearTimeout(silenceWarnT)
  if (ws && ws.readyState === 1) closeWsQuiet(ws)
  ws = null
  answers.value[qIndex.value] = (finalText.value || transcript.value || '').trim()
  if (answers.value[qIndex.value]) log(`旅程：第 ${qIndex.value + 1}/${QUESTIONS.length} 问讲完（${answers.value[qIndex.value].length} 字）`, 'ok')
  else log(`旅程：第 ${qIndex.value + 1} 问没有内容，跳过`, 'evt')
  if (qIndex.value < QUESTIONS.length - 1) {
    screen.value = 'nextq'
    nextQCountdown.value = 3
    nextQT = setInterval(() => {
      nextQCountdown.value--
      if (nextQCountdown.value <= 0) { clearInterval(nextQT); nextQT = null; startQuestion(qIndex.value + 1) }
    }, 1000)
  } else summarizeAll()
}

function skipNextQ() {              // 过渡屏「现在就开始」：跳过倒计时
  clearInterval(nextQT); nextQT = null
  startQuestion(qIndex.value + 1)
}

function abortSpeak() {             // 异常中止：回 01
  stopFlag = true
  clearTimeout(silenceWarnT)
  if (mic) { mic.stop(); mic = null }
  if (ws && ws.readyState === 1) closeWsQuiet(ws)
  ws = null; screen.value = 'idle'
}

function summarizeAll() {           // 三问讲完：合并整理 -> 04 -> 05
  if (['summarizing', 'journal', 'editing', 'confirm'].includes(screen.value)) return   // 防重入
  if (ws && ws.readyState === 1) ws.close()
  ws = null
  screen.value = 'summarizing'
  const segs = answers.value.map(s => (s || '').trim()).filter(Boolean)
  if (!segs.length) {
    log('旅程：三个问题都没有内容，请重新开始', 'err')
    screen.value = 'idle'; qIndex.value = 0
    return
  }
  setTimeout(() => {
    journal.value = buildJournal(segs)          // 分段输入：发现 = 每问一句
    changes.value = []
    log('旅程：手记已生成（合并 ' + segs.length + ' 问）- 「' + journal.value.title + '」', 'ok')
    screen.value = 'journal'
  }, 1400)
}

/* ---- 06 语音修改轮：短会话收指令，静音 2s 自动应用；也支持文本输入兜底 ---- */
let ews = null, emic = null, eSent = 0, eSilence = 0, eHasVoice = false, eApplyTimer = null

function resetEditLoop() {
  if (eApplyTimer) { clearTimeout(eApplyTimer); eApplyTimer = null }
  if (emic) { emic.stop(); emic = null }
  if (ews && ews.readyState === 1) ews.close()
  ews = null; eSent = 0; eSilence = 0; eHasVoice = false
}

async function startEditVoice() {   // 进入语音修改监听
  resetEditLoop()
  editUtterance.value = ''; editApplied.value = ''
  try {
    ews = new WebSocket(`${WS_HOST_LEGACY}/asr/v1/realtime?api_key=${encodeURIComponent(store.apiKey)}`)
    ews.onopen = () => {
      screen.value = 'editing'
      ews.send(JSON.stringify({type: 'session.update', session: {language: 'auto'}}))
      const sendJSON = f => { if (ews.readyState === 1) { eSent++
        ews.send(JSON.stringify({type: 'input_audio_buffer.append', audio: b64frame(f)})) } }
      emic = new Mic()
      emic.start(pcm => {
        let sum = 0; for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i]
        const rms = Math.sqrt(sum / pcm.length) / 32768
        if (rms > 0.015) { eHasVoice = true; eSilence = 0 }
        else if (eHasVoice) {
          eSilence += pcm.length / SR * 1000
          if (eSilence >= 2000 && editUtterance.value) applyEditDone(editUtterance.value)   // 静音 2s 自动应用
        }
        for (let i = 0; i < pcm.length; i += FRAME) sendJSON(pcm.subarray(i, i + FRAME))
      }).catch(e => { log('旅程：修改轮麦克风失败 - ' + e.message + '，可改用文本输入', 'err'); resetEditLoop() })
    }
    ews.onmessage = ev => {
      let d; try { d = JSON.parse(ev.data) } catch (e) { return }
      if (d.type === 'transcription.delta') editUtterance.value = d.text || d.delta || ''
      else if (d.type === 'error') log('旅程：修改轮服务端错误 - ' + (d.message || ''), 'err')
    }
    ews.onclose = () => { ews = null }
    ews.onerror = () => log('旅程：修改轮 WS 错误', 'err')
  } catch (e) { log('旅程：修改轮 - ' + e.message, 'err'); resetEditLoop() }
}

function applyEditDone(utterance) { // 解析并应用修改指令（语音/文本共用）
  resetEditLoop()
  const r = applyEdit(journal.value, utterance)
  if (!r) {
    editApplied.value = '没听懂这句修改（示例：标题改得轻松一点 / 加一句明年再来）'
    log('旅程：修改指令未识别 - ' + utterance, 'evt')
    return
  }
  journal.value = r.journal
  changes.value = r.changes
  editApplied.value = '已更新 ' + r.changes.length + ' 处'
  log('旅程：修改已应用（' + r.changes.map(c => c.label).join('、') + '）', 'ok')
}

function finishEditing() {          // 06 -> 07
  resetEditLoop()
  changes.value = []                // 确认屏不显示编辑标记（设计稿 07）
  screen.value = 'confirm'
}

function doPrint() {                // 07 -> 打印（模拟）-> 08（三问已全部讲完，打印即终点）
  screen.value = 'printing'
  printMsg.value = '正在打印…（演示：打印为模拟）'
  log('旅程：已确认打印（演示环境模拟出纸）', 'ok')
  setTimeout(() => {
    printMsg.value = ''
    screen.value = 'done'
  }, 1200)
}

function startQuestion(i) {          // 进入第 i 问的讲述（01 卡片/主按钮/过渡屏自动跳共用）
  clearInterval(nextQT); nextQT = null; nextQCountdown.value = 0
  resetEditLoop(); abortSpeak()      // 清上一问会话与修改轮状态（abortSpeak 会短暂回 idle，随后即开新会话）
  qIndex.value = Math.max(0, Math.min(i, QUESTIONS.length - 1))
  transcript.value = ''; finalText.value = ''; journal.value = null
  changes.value = []; editUtterance.value = ''; editApplied.value = ''; editTextInput.value = ''
  log(`旅程：第 ${qIndex.value + 1}/${QUESTIONS.length} 问「${QUESTIONS[qIndex.value].label}」开始`)
  beginSpeak()
}

function resetAll() {               // 08 -> 01 重新开始（清三问答案，回第一问）
  clearInterval(nextQT); nextQT = null; nextQCountdown.value = 0
  resetEditLoop(); abortSpeak()
  qIndex.value = 0
  answers.value = ['', '', '']
  transcript.value = ''; finalText.value = ''; journal.value = null
  changes.value = []; editUtterance.value = ''; editApplied.value = ''; editTextInput.value = ''
  screen.value = 'idle'
  log('旅程：已重置，从第一问重新开始')
}

onBeforeUnmount(() => { resetEditLoop(); abortSpeak(); clearTimeout(finishTimer); clearInterval(nextQT) })
</script>

<template>
  <section class="card">
    <div class="row" style="margin:0 0 10px;border-bottom:1px solid var(--line);padding-bottom:10px">
      <h2 style="margin:0">高交会 · 未来手记</h2>
      <span class="tag">☎ 听筒</span>
      <span class="tag">讲述 — 修改 — 打印（8 屏旅程）</span>
      <label class="sub" style="display:inline-flex;gap:4px;align-items:center">
        停顿切安抚屏 <input type="number" v-model="pauseSec" min="1" max="10" step="0.5" style="width:48px">秒</label>
    </div>

    <!-- 01 获得问题 -->
    <div v-if="screen === 'idle'" style="text-align:center;padding:26px 10px">
      <div class="sub" style="font-size:13px">☎ 听筒已接通</div>
      <div style="font-size:26px;line-height:1.6;font-weight:600;margin:18px 0 6px">
        <div v-for="(l, i) in IDLE_Q" :key="i">{{ l }}</div>
      </div>
      <div class="sub">想到什么，就从哪里说起 · 讲完一问，自动进入下一问</div>
      <!-- 三问竖排卡片：点任意一问，从该问开始连讲 -->
      <div style="display:flex;flex-direction:column;gap:10px;max-width:420px;margin:20px auto">
        <button v-for="(q, i) in QUESTIONS" :key="q.label"
          style="display:flex;align-items:center;gap:12px;padding:14px 16px;border:1px solid var(--line);
            border-radius:12px;background:var(--panel2);cursor:pointer;text-align:left"
          @click="startQuestion(i)">
          <span style="font-size:18px;font-weight:600;color:var(--acc)">{{ i + 1 }}</span>
          <span>
            <span style="display:block;font-size:15px;font-weight:600">{{ q.label }}</span>
            <span class="sub" style="display:block;font-size:12px">{{ q.hint }}</span>
          </span>
        </button>
      </div>
      <div class="sub" style="color:var(--acc)">直接对着听筒说就好 · 说「我说完了」进入下一问</div>
      <button class="act" style="margin-top:14px" @click="startQuestion(0)">开始讲述（从第一问）</button>
    </div>

    <!-- 02 自由讲述（含三问竖排进度清单） -->
    <div v-else-if="screen === 'listening'">
      <!-- 三问竖排清单：已讲完打勾、当前问高亮 -->
      <div style="border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:12px">
        <div v-for="(q, i) in QUESTIONS" :key="q.label"
          :style="{display:'flex',alignItems:'center',gap:'10px',padding:'9px 14px',fontSize:'14px',
            background: i === qIndex ? 'rgba(47,111,237,.06)' : 'transparent',
            borderBottom: i < QUESTIONS.length - 1 ? '1px solid var(--line)' : 'none',
            color: i < qIndex ? 'var(--dim)' : 'inherit'}">
          <span :style="{width:'20px',height:'20px',borderRadius:'50%',flex:'0 0 20px',display:'inline-flex',
            alignItems:'center',justifyContent:'center',fontSize:'12px',
            border: i === qIndex ? '1px solid var(--acc)' : '1px solid var(--line)',
            color: i < qIndex ? 'var(--ok)' : i === qIndex ? 'var(--acc)' : 'var(--dim)',
            background: i < qIndex ? 'rgba(23,138,76,.08)' : 'transparent'}">
            {{ i < qIndex ? '✓' : i + 1 }}</span>
          <span :style="{textDecoration: i < qIndex ? 'line-through' : 'none',
            fontWeight: i === qIndex ? 600 : 400}">{{ q.label }}</span>
          <span v-if="i === qIndex" class="tag" style="margin-left:auto;color:var(--acc);border-color:var(--acc)">正在听</span>
          <span v-else-if="i < qIndex" style="margin-left:auto;font-size:12px;color:var(--ok)">已讲完</span>
        </div>
      </div>
      <div class="sub">正在聆听 · 第 {{ qIndex + 1 }}/{{ QUESTIONS.length }} 问</div>
      <div style="font-size:30px;font-weight:600;margin:6px 0">我在听</div>
      <div class="sub">想到什么，就慢慢说</div>
      <!-- 真实麦克风音量条：说话时应明显起伏；始终不动=输入设备/权限有问题 -->
      <div class="row" style="justify-content:center;gap:3px;height:26px;align-items:center">
        <span v-for="i in 9" :key="i" :style="{display:'inline-block',width:'3px',borderRadius:'2px',
          background:'var(--acc)',height:(4+micLevel*22*(0.45+0.55*Math.abs(Math.sin(i*1.3))))+'px'}"></span>
      </div>
      <div class="sub" style="font-size:11px">说话时上面的音量条应有起伏</div>
      <div style="background:var(--panel2);border:1px dashed #c6ccd6;border-radius:10px;padding:12px;margin:10px 0">
        <div class="sub" style="margin-bottom:4px">实时记录</div>
        <div style="font-size:16px;line-height:1.8;white-space:pre-wrap;min-height:56px">{{ transcript || '（正在等你开口…）' }}</div>
      </div>
      <div class="sub">可以停顿，想好了再继续</div>
      <div class="row" style="justify-content:center;margin-top:10px">
        <button class="act" style="padding:12px 44px" @click="finishSpeak()">我说完了</button>
      </div>
      <div class="sub" style="text-align:center">
        {{ qIndex < QUESTIONS.length - 1 ? '说「我说完了」，或点击按钮进入下一问' : '说「我说完了」，或点击按钮生成手记' }}</div>
    </div>

    <!-- 03 暂时停顿（不自动结束） -->
    <div v-else-if="screen === 'pause'">
      <div class="sub" style="border:1px solid var(--line);border-radius:999px;padding:3px 12px;display:inline-block">暂时停顿 · 仍在聆听</div>
      <div style="font-size:28px;font-weight:600;line-height:1.5;margin:12px 0">慢慢想，<br>我还在</div>
      <div class="sub">想好了，接着说就好</div>
      <div class="row" style="justify-content:center;gap:8px;color:var(--acc)">
        <span style="display:inline-block;width:60%;height:2px;background:var(--line)"></span>
        <span style="width:6px;height:6px;border-radius:50%;background:var(--acc);display:inline-block"></span>
        <span style="width:6px;height:6px;border-radius:50%;background:var(--acc);display:inline-block"></span>
        <span style="width:6px;height:6px;border-radius:50%;background:var(--acc);display:inline-block"></span>
        <span style="display:inline-block;width:60%;height:2px;background:var(--line)"></span>
      </div>
      <div style="background:var(--panel2);border:1px dashed #c6ccd6;border-radius:10px;padding:12px;margin:10px 0">
        <div class="sub" style="margin-bottom:4px">刚刚说到</div>
        <div style="font-size:16px;line-height:1.8">{{ (transcript || '').trim().split(/[。！？]/).filter(Boolean).slice(-1)[0] || '…' }}</div>
      </div>
      <div class="sub" style="color:var(--warn)">不会因为安静而自动结束</div>
      <div class="row" style="justify-content:center;margin-top:10px">
        <button class="act" style="padding:12px 44px" @click="finishSpeak()">我说完了</button>
      </div>
      <div class="sub" style="text-align:center">讲完后，再告诉我</div>
    </div>

    <!-- 03b 下一问过渡：一问讲完自动切，3 秒倒计时（可跳过） -->
    <div v-else-if="screen === 'nextq'" style="text-align:center;padding:26px 10px">
      <div class="sub" style="border:1px solid var(--ok);color:var(--ok);border-radius:999px;padding:3px 12px;display:inline-block">
        ✓ 第 {{ qIndex + 1 }}/{{ QUESTIONS.length }} 问 · 已讲完</div>
      <div style="font-size:26px;font-weight:600;margin:14px 0 8px">这一问，聊完了</div>
      <div class="sub">接下来，我们聊聊</div>
      <div style="font-size:20px;font-weight:600;color:var(--acc);margin:8px 0 4px">「{{ QUESTIONS[qIndex + 1].label }}」</div>
      <div class="sub" style="color:var(--dim);margin-top:2px">{{ QUESTIONS[qIndex + 1].hint }}</div>
      <div class="sub" style="color:var(--acc);margin-top:14px">{{ nextQCountdown }} 秒后自动开始</div>
      <div class="row" style="justify-content:center;margin-top:10px">
        <button class="act" style="padding:12px 36px" @click="skipNextQ()">现在就开始</button>
      </div>
    </div>

    <!-- 04 完成讲述·整理中 -->
    <div v-else-if="screen === 'summarizing'" style="text-align:center;padding:30px 10px">
      <div class="sub" style="border:1px solid var(--ok);color:var(--ok);border-radius:999px;padding:3px 12px;display:inline-block">✓ 讲述已完成</div>
      <div style="font-size:26px;font-weight:600;margin:14px 0 8px">三问都聊完了，<br>这段讲述，记下了</div>
      <div class="sub">“我说完了”</div>
      <div style="margin:18px 0;font-size:15px">正在整理你的手记</div>
      <div class="row" style="justify-content:center;gap:6px">
        <span v-for="i in 3" :key="i" style="width:8px;height:8px;border-radius:50%;background:var(--acc);display:inline-block"></span>
      </div>
      <div class="sub" style="margin-top:16px">把你的发现和原话，认真留下</div>
      <div class="sub" style="margin-top:6px">生成后，你可以继续修改</div>
    </div>

    <!-- 05/06/07 手记卡（journal / editing / confirm 共用；变更标记仅 editing 显示） -->
    <div v-else-if="['journal', 'editing', 'confirm', 'printing'].includes(screen)">
      <div class="sub" v-if="screen === 'journal'">手记已生成</div>
      <div class="sub" v-else-if="screen === 'editing'" style="color:var(--ok)">
        {{ editApplied || '正在聆听你的修改…' }}</div>
      <div class="sub" v-else-if="screen === 'confirm'">手记已就绪</div>
      <div class="sub" v-else>打印完成</div>

      <div style="font-size:24px;font-weight:600;margin:6px 0" v-if="screen === 'journal'">你的未来手记</div>
      <div style="font-size:24px;font-weight:600;margin:6px 0" v-else-if="screen === 'editing'">按你说的，改好了</div>
      <div style="font-size:24px;font-weight:600;margin:6px 0" v-else-if="screen === 'confirm'">最后看一眼</div>
      <div style="font-size:24px;font-weight:600;margin:6px 0" v-else>把今天的未来，<br>带回家</div>

      <!-- 06 语音指令气泡 -->
      <div v-if="screen === 'editing'" style="border:1px solid var(--acc);border-radius:12px;padding:8px 12px;
        background:rgba(47,111,237,.04);font-size:14px;line-height:1.7;white-space:pre-wrap">
        <span class="sub">你想怎么改：</span>{{ editUtterance || '（说出修改指令，停 2 秒自动生效…）' }}
      </div>
      <div v-if="screen === 'confirm'" class="sub">确认后，才会打印</div>

      <!-- 手记纸卡 -->
      <div v-if="journal && screen !== 'printing'" style="background:#fffdf8;border:1px solid #e8e2d4;
        border-radius:12px;padding:18px 20px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.04)">
        <div class="sub" style="text-align:center;letter-spacing:2px">{{ journal.masthead }}</div>
        <div style="text-align:center;font-size:20px;font-weight:600;margin:10px 0 4px;
          background:rgba(23,138,76,.08)">
          {{ journal.title }}
          <span v-if="screen === 'editing' && journal.titleChanged" class="tag" style="color:var(--acc);border-color:var(--acc)">标题已修改</span>
        </div>
        <div class="sub" style="margin-top:12px">我的发现</div>
        <div style="font-size:15px;line-height:1.9">
          <div v-for="(d, i) in journal.discoveries" :key="i">0{{ i + 1 }}&nbsp;&nbsp;{{ d }}</div>
        </div>
        <div class="sub" style="margin-top:12px">{{ journal.quoteLabel }}</div>
        <div style="font-size:15px;line-height:1.9">“{{ journal.quote }}”</div>
        <div v-if="journal.added" style="font-size:15px;line-height:1.9;margin-top:6px;
          background:rgba(23,138,76,.08)">
          {{ journal.added.text }}
          <span v-if="screen === 'editing'" class="tag" style="color:var(--acc);border-color:var(--acc)">新增</span>
        </div>
        <div class="row" style="margin-top:14px">
          <span v-for="k in journal.keywords" :key="k" class="tag">{{ k }}</span>
        </div>
      </div>

      <!-- 各屏操作区 -->
      <template v-if="screen === 'journal'">
        <div class="sub">直接说，你想怎么改</div>
        <div class="sub" style="border:1px dashed var(--acc);color:var(--acc);border-radius:999px;
          padding:3px 12px;display:inline-block">比如：标题改得轻松一点</div>
        <div class="row" style="margin-top:12px">
          <button class="act" @click="startEditVoice()">我想改一改</button>
          <button class="act ghost" @click="screen = 'confirm'">内容没问题</button>
        </div>
      </template>
      <template v-else-if="screen === 'editing'">
        <div class="sub">还想调整，可以继续说</div>
        <div class="row" style="margin-top:10px">
          <button class="act" @click="finishEditing()">修改完成，去确认</button>
          <button class="mini" @click="startEditVoice()">重新说修改</button>
        </div>
        <div class="row">
          <input type="text" v-model="editTextInput" placeholder="无麦克风？输入指令，如：加一句明年再来"
            style="flex:1;min-width:220px" @keyup.enter="applyEditDone(editTextInput)">
          <button class="mini" @click="applyEditDone(editTextInput)">应用</button>
        </div>
      </template>
      <template v-else-if="screen === 'confirm'">
        <div class="row" style="margin-top:12px">
          <button style="background:var(--acc);border:none;color:#fff;padding:14px 0;width:100%;
            border-radius:10px;font-size:17px;cursor:pointer" @click="doPrint()">确认并打印</button>
        </div>
        <div class="row" style="justify-content:center">
          <button class="act ghost" @click="startEditVoice()">返回修改</button>
        </div>
      </template>

      <!-- 08 打印完成（含取走指引） -->
      <template v-if="screen === 'printing' || screen === 'done'">
        <div v-if="printMsg" class="sub" style="text-align:center;margin-top:10px">{{ printMsg }}</div>
        <template v-if="screen === 'done'">
          <div class="row" style="justify-content:center;margin-bottom:8px">
            <span class="tag" style="color:var(--ok);border-color:var(--ok)">✓ 三个问题 · 一张手记</span>
          </div>
          <div style="text-align:center;margin:14px 0;font-size:15px;font-weight:600">请从下方取走手记</div>
          <div style="text-align:center;font-size:34px;color:var(--acc)">⬇</div>
          <div class="sub" style="text-align:center;margin-top:16px">☎ 取走后，请挂好听筒</div>
          <div class="sub" style="text-align:center;margin-top:14px;color:var(--ok)">三个问题都聊完了，谢谢你</div>
          <div class="row" style="justify-content:center;margin-top:10px">
            <button class="act ghost" @click="resetAll()">重新开始</button>
          </div>
        </template>
      </template>
    </div>

    <!-- 底部三段旅程 -->
    <div class="row" style="justify-content:center;gap:18px;border-top:1px solid var(--line);
      padding-top:12px;margin-top:14px">
      <span v-for="(s, i) in stages" :key="s.name"
        :style="{color: s.state === 'inactive' ? 'var(--dim)' : s.state === 'active' ? 'var(--acc)' : 'var(--ok)',
          fontWeight: s.state === 'active' ? 600 : 400, fontSize: '13px'}">
        {{ s.state === 'checked' ? '✓ ' : '' }}{{ s.name }}{{ i < 2 ? ' —' : '' }}
      </span>
    </div>
  </section>
</template>

