import { store } from './store.js'

const EN = {
  'Amphion 语音工作台': 'Amphion Voice Workspace',
  '空闲': 'Idle', '录音中': 'Recording', '音频文件测试': 'Audio file test',
  '简洁日志': 'Compact logs', '检查': 'Check', '和 2036 对话': 'Conversation with 2036',
  '竖屏体验': 'Portrait view', '连接设置': 'Connection settings', '其他工作台': 'Other workspaces',
  '运行记录': 'Run log', '语音网关密钥': 'Voice gateway key', '保存设置': 'Save settings',
  '关闭设置': 'Close settings', '检查手记与声音服务': 'Check note and voice services', '检查中…': 'Checking…',
  '未来回信': 'Future reply', '本人声音': 'My voice', '尚未检查': 'Not checked yet',
  '网关状态未知': 'Gateway status unknown', '识别服务健康检查通过': 'ASR health check passed',
  '识别服务健康检查失败': 'ASR health check failed', '网关异常': 'Gateway error',
  '一通跨越时间的电话': 'A call across time', '影像出处': 'Image credits',
  '开始通话': 'Start the call', '开始新的通话': 'Start a new call', '用我的声音，听见未来的回信': 'Hear the reply in my voice',
  '我期待的 2036': 'What I Hope for in 2036', '未来，从这个想法开始': 'The Future Starts with This Idea', '把今天，留给未来': 'Keeping Today for Tomorrow', '今天，我遇见了未来': 'Today, I Met the Future',
  '十年后的世界，你想怎样生活？': 'In the world ten years from now, how do you want to live?',
  '对 2036 的期待': 'What I hope for in 2036', '重试声音': 'Retry voice', '打印手记': 'Print note',
  '重试插画': 'Retry illustration', '正在画下你的期待…': 'Drawing your expectation…', '重新整理': 'Regenerate note',
  '先看手记': 'View the note first', '重新开始': 'Start over', '已收到手记': 'I received the note',
  '返回预览': 'Back to preview', '正在等待下一句话': 'Waiting for your next sentence', '可以开始说话了': 'You can start speaking',
  '讲述已暂停': 'Your story is paused', '写下你的期待': 'Write your expectation', '正在连接': 'Connecting',
  '你的完整讲述': 'Your full story', '已收到声音，正在识别': 'Audio received, transcribing', '等待你的声音': 'Waiting for your voice',
  '你的讲述': 'Your story', '实时讲述': 'Live transcript', '你的第一句话，会出现在这里。': 'Your first sentence will appear here.',
  '2036 年，我希望……': 'In 2036, I hope…', '我说完了': "I'm finished", '继续录音': 'Continue recording',
  '改用语音': 'Use voice instead', '改用文字': 'Use text instead', '写完后，把今天留在手记里。': 'When you are done, leave today in the note.',
  '还想说些什么，我在听。': "If there is more, I'm listening.", '结束这次通话': 'End this call',
  '一封穿越时空的信，正在飞向 2036': 'A letter across time is flying toward 2036', '这一刻，留住了。': 'Keep this moment.',
  '正在整理你的讲述': 'Shaping your story', '正在收好你的最后一句话': 'Keeping your last sentence', '正在整理你对 2036 的期待': 'Shaping your hopes for 2036', '正在把你的想象画进手记': 'Drawing your imagination into the note', '正在用你的声音，接通这封来自未来的回信': 'Connecting the reply from the future in your voice',
  '手记已经准备好，声音可以稍后重试。': 'The note is ready. You can retry the voice later.', '打印窗口已关闭，请确认是否收到手记。': 'The print window closed. Please confirm that you received the note.', '等待打印操作完成。': 'Waiting for printing to finish.', '声音已经生成，浏览器需要一次点击才能开启播放。': 'Your voice is ready. The browser needs one click to start playback.',
  '带上这份回信，慢慢走向你的未来。': 'Take this reply with you, and walk gently toward your future.',
  '播放我的声音': 'Play my voice', '暂停播放': 'Pause playback', '关闭提示': 'Dismiss notice', '打开设置': 'Open settings',
  '声音克隆对话': 'Voice cloning conversation', '多人对话工作台': 'Multi-speaker workspace', '未来手记旅程': 'Future note journey',
  '声音克隆': 'Voice cloning', '接入文档 ↗': 'API docs ↗', '连接': 'Connection', '未连接': 'Not connected',
  '连接失败': 'Connection failed', '本机连接信息已清除': 'Local connection details cleared', '连接并读取声纹': 'Connect and load voices',
  '注册声纹': 'Enroll voiceprint', '声纹档案名': 'Voiceprint profile name', '添加音频': 'Add audio', '清空片段': 'Clear clips',
  '尚未添加语句。可添加多段，每段保持 5–10 秒。': 'No clips yet. Add several clips, keeping each 5–10 seconds.',
  '每段 5–10 秒': '5–10 seconds each', '已获得本人明确授权，用于声纹身份识别': 'I have clear consent to use this voice for identification',
  '创建后参与本次识别': 'Use this profile in this session', '默认加入实时识别的目标声纹': 'Add it to the live recognition targets by default',
  '创建声纹档案': 'Create voiceprint profile', '正在创建…': 'Creating…', '实时对话': 'Live conversation',
  '声纹': 'Voiceprints', '开始录制': 'Start recording', '保持单人、安静、距离稳定。': 'Keep one speaker, a quiet room, and a steady distance.', '选择声纹或开启边聊边采集后开始': 'Select a voiceprint or enable enroll while talking to begin', '事件日志': 'Event log', '清空': 'Clear', '（暂无日志）': '(No logs yet)',
  '等待选择目标人': 'Waiting for target selection', '最新优先': 'Latest first', '识别中': 'Transcribing', '已确认': 'Confirmed',
  '选择目标声纹，或开启“边聊边采集”后直接开始。': 'Select a voiceprint, or turn on “enroll while talking” to begin.',
  '边聊边采集': 'Enroll while talking', '锁定目标': 'Lock targets', '识别热词': 'Recognition hotwords', '内置行业词包': 'Built-in domain words',
  '不使用': 'None', '金融': 'Finance', '教育': 'Education', '互联网 / 技术': 'Internet / technology',
  '自定义热词': 'Custom hotwords', '连接后读取声纹档案。': 'Connect to load voiceprint profiles.', '删除档案': 'Delete profile',
  '留空时经本地服务 /proxy 同源转发；也可填 https://amphion.top 直连。': 'Leave blank to use the local same-origin /proxy; or enter https://amphion.top for a direct connection.', '未启用': 'Not enabled', '开启后不使用预选声纹；匿名分角色，达到 5 秒后录入并上锁': 'Uses anonymous speaker roles; enroll and lock a role after 5 seconds',
  '接口': 'Endpoints', '声纹注册': 'Voiceprint enrollment', '声纹管理': 'Voiceprint management', '鉴权': 'Authentication',
  '流式转写': 'Streaming transcription', '音频规格': 'Audio format', '多人对话': 'Multi-speaker conversation',
  '你的声音，替我说话 —— 克隆音色注册 + 实时转写 + 克隆音色复述': 'Your voice, speaking for me — voice registration, live transcription, and cloned-voice playback',
  '说话人1 · 克隆我的声音': 'Speaker 1 · Clone my voice', '说话人2 · 用 TA 的声音说话': 'Speaker 2 · Speak with that voice',
  '参考录音：5–15 秒清晰的单人讲话。请仅使用本人或已获授权的声音。': 'Reference audio: 5–15 seconds of clear speech from one person. Use only an authorized voice.',
  '录制参考音频': 'Record reference audio', '未录制': 'Not recorded', '或选择文件': 'Or choose a file',
  '音色名（英文/数字/下划线）': 'Voice name (letters, numbers, underscores)', '注册复刻音色': 'Register cloned voice',
  '音色列表': 'Voice list', '刷新': 'Refresh', '删除': 'Delete', '合成后端': 'Synthesis backend', '由当前语音服务提供': 'Provided by the current voice service',
  '试听文本…': 'Preview text…', '试听': 'Preview', '取消连接': 'Cancel connection', '■ 停止会话': '■ Stop session',
  '🎤 开始对话': '🎤 Start conversation', '开始后，说出的话将实时转写，并以克隆音色逐句复述…': 'After starting, your words are transcribed live and repeated sentence by sentence in the cloned voice…',
  '重播': 'Replay', '重新合成并播放': 'Synthesize and play again', '开始录音': 'Start recording', '结束': 'Finish',
  '结束并出全文': 'Finish and show full transcript', '音频文件测试': 'Test an audio file', '自动流转': 'Auto-advance',
  '静音判停': 'Stop after silence', '接口一 流式转写': 'Endpoint 1 · Streaming transcription', '接口二 多人说话人分离': 'Endpoint 2 · Multi-speaker separation',
  '完整转写会显示在这里': 'The full transcript will appear here', '实时转写会显示在这里…': 'Live transcription will appear here…', '取消自动收尾': 'Cancel auto-finish',
  '接口三（A）声纹注册与音色克隆': 'Endpoint 3A · Voiceprint enrollment and cloning', '接口三（B）克隆合成': 'Endpoint 3B · Cloned-voice synthesis',
  '合成并播放': 'Synthesize and play', '删除选中': 'Delete selected', '点击刷新音色列表': 'Click to refresh voice list',
  '本页可留空': 'Optional on this page', '本机记住连接': 'Remember connection on this device', '清除': 'Clear',
  '注册后即成可复刻音色': 'Ready to clone after registration', '音色配额': 'Voice quota', '删除选中': 'Delete selected', '本地 Qwen3-TTS-1.7B': 'Local Qwen3-TTS-1.7B', '火山 seed-iclv2': 'Volcengine seed-iclv2',
  '播放该录音': 'Play this recording', '停止播放': 'Stop playback', '删除该录音': 'Delete this recording',
  '全屏体验': 'Fullscreen', '链接已复制': 'Link copied', '复制体验链接': 'Copy experience link', '返回普通页面': 'Back to standard view',
  '切换语言': 'Switch language', '和 2036 对话竖屏体验': 'Conversation with 2036 portrait experience',
  '竖屏体验': 'Portrait experience', '未来来电 · FUTURE CALL': 'Future call · FUTURE CALL',
  '蓝牙耳机与第一代无线耳机': 'Bluetooth earbuds and the first wireless earbuds', '围棋棋盘与落子': 'A Go board and a stone', '城市中的无人驾驶汽车': 'Self-driving cars in the city', '驶向太空的红色跑车': 'A red sports car heading into space', '老式蓝牙耳机与 AirPods 的对比': 'A comparison of an old Bluetooth earpiece and AirPods', '无人驾驶汽车与飞车的对比': 'A comparison of a self-driving car and a flying car', '真人下棋与 AI 下棋的对比': 'A comparison of a human Go player and an AI Go player', '从一只耳朵，到一对耳机': 'From one ear to both', '从有人驾驶，到驶向天空': 'From self-driving to the sky', '从人的落子，到 AI 的落子': 'From a human move to an AI move', '老式蓝牙耳机': 'Bluetooth 4.1 earpiece', '无人驾驶': 'Self-driving car', '飞车想象': 'Flying car', '真人下棋': 'Human Go player', 'AI 下棋': 'AI Go player',
  '一部红色转盘座机电话': 'A red rotary telephone', '同一人可录多段，每段 5–10 秒。': 'One person can record several clips, 5–10 seconds each.', '开始识别': 'Start recognition', '二进制帧': 'binary frames', '— 音色列表 —': '— Voice list —', '克隆音色就绪后，点击麦克风开始——说出的话将以该音色实时复述': 'When the cloned voice is ready, click the microphone to start — your words will be repeated in that voice', '给今天的自己留一句话，慢慢来，也可以继续向前。': 'Leave a line for yourself today. Take your time, and keep moving forward.',
  '① 说话人1 · 克隆我的声音': '① Speaker 1 · Clone my voice', '② 说话人2 · 用 TA 的声音说话': '② Speaker 2 · Speak with that voice',
  '高交会 · 安菲翁科技': 'Hi-Tech Fair · Amphion Technology', '私人珍藏版': 'Private edition', '和 2036 对话纪念便签': 'Conversation with 2036 keepsake',
  '我的未来想象': 'My future imagination', '来自未来的回音': 'An echo from the future', '这通电话\n关于': 'This call\nwas about',
  '从今天出发': 'Starting today', '寄给 2036 的自己': 'To myself in 2036', '讲述已留存，等待整理': 'Story saved, waiting to be shaped',
  '以后的我，留给现在的我。': 'From my future self, to me today.', 'A Letter to 2036': 'A Letter to 2036',
  '正在开启麦克风': 'Opening microphone', '正在准备倾听': 'Preparing to listen', '正在接通语音服务': 'Connecting voice service',
  '一段关于未来的想象': 'A thought about tomorrow', '01 / 回看十年': '01 / Looking back', '02 / 留下期待': '02 / Your hopes', '03 / 给未来的信': '03 / Letter to the future',
  '把今天的一点期待，': 'Share a little hope from today,', '说给十年后的世界。': 'with the world ten years from now.', '不用想好答案，从一个小小的愿望开始。': 'Start with one small wish.',
  '开始体验': 'Start experience', '用我的声音，听见未来的回信（可选）': 'Hear the future reply in my voice (optional)',
  '默认只转写讲述。勾选后才会尝试采集本人音色；': 'By default, only your words are transcribed. Check this to capture your voice;',
  '声音暂不可用时，仍可生成文字手记。': 'a written note is still available if voice playback fails.',
  '回看过去十年': 'Looking back at the past decade', '变化，曾经也是想象。': 'Every change began as an idea.', '跳过动画': 'Skip animation',
  '留一点想象给未来': 'Leave a thought for the future', '十年后的世界，': 'The world in ten years,', '你希望怎样生活？': 'how do you hope to live?',
  '可以是一件小事，也可以是一个大胆的念头。': 'It can be a small detail or a bold idea.',
  '正在连接麦克风': 'Connecting microphone', '连接完成后，就可以开始说话。': 'You can speak as soon as the connection is ready.',
  '回到最新一句': 'Jump to latest', '可向上滚动查看': 'Scroll up to review', '你刚刚说': 'You just said', '你的期待': 'Your hopes',
  '第一句话，会从这里开始。': 'Your first words will appear here.', '已收到声音，正在识别…': 'Audio received, transcribing…',
  '正在处理 · 麦克风已关闭': 'Processing · microphone off', '只记录你此刻想留下的话': 'Only the words you choose to leave here are recorded',
  '正在整理…': 'Shaping your note…', '文字输入': 'Type instead', '重新连接': 'Reconnect', '结束对话': 'End conversation',
  '给你的回信': 'Your reply', '来自未来的一句话': 'A note from the future', '正在播放回信': 'Playing your reply',
  '还在认真整理，完整讲述已保留，请稍候。': 'Still shaping your note. Your full story is saved.',
  '你的讲述已收到，整理好后会呈现给你。': 'Your story is saved. Your note will appear when it is ready.',
  '随时可以改回语音，已写下的内容会保留。': 'Switch back to voice anytime. Your writing will remain.',
  '说完后点下方按钮，或说“我说完了”。': 'When finished, use the button below or say "I am done".',
  '你可以重新连接，也可以用文字继续。': 'Reconnect or continue in writing.',
  '讲述已保留': 'Your story is saved', '回信还没准备好，你可以直接重试。': 'The reply is not ready. You can retry now.',
  '返回首页': 'Back to home', '插画生成超时，文字手记已保留。': 'Illustration timed out. Your note is saved.',
  '回信生成超时，完整讲述已保留，可以重新整理。': 'The reply timed out. Your full story is saved; please retry.',
  '正在接通': 'Connecting', '如浏览器询问权限，请选择允许使用麦克风。': 'If your browser asks, allow microphone access.',
  '首次使用需要加载片刻，准备好后会提醒你开始。': 'The first use may take a moment to load. We will tell you when it is ready.',
  '麦克风已就绪，正在等待语音服务。': 'The microphone is ready; waiting for the voice service.',
  '回信暂时无法生成，完整讲述已保留。': 'The reply could not be generated yet. Your full story is saved.',
  '回信内容不完整，完整讲述已保留，请重新整理。': 'The reply was incomplete. Your full story is saved; please try again.',
  '这次回信太长，完整讲述已保留，请重新整理。': 'This reply was too long. Your full story is saved; please try again.',
  '插画暂时未能生成，可以重试或打印文字手记。': 'The illustration is not ready. You can retry or print the text note.',
  '未收到有效插画，请重试。': 'No valid illustration was received. Please retry.',
  '本地回信服务未连接': 'Local reply service is not connected', '未配置文本模型，无法生成摘要与未来回信': 'No text model configured; summaries and future replies are unavailable',
  '未填写语音网关密钥': 'Voice gateway key is missing', '本人声音模型正在加载，请稍后检查。': 'The voice model is loading. Check again shortly.',
  '上传复刻中…': 'Uploading for cloning…', '注册中…': 'Registering…', '上传成功': 'Upload succeeded', '失败：': 'Failed: ', '文件需小于 10 MB': 'The file must be smaller than 10 MB', '参考音频需为 5–15 秒': 'Reference audio must be 5–15 seconds', '解码失败：': 'Decode failed: ', '音色名需为英文/数字/下划线': 'The voice name must use letters, numbers, or underscores', '音色列表读取失败：': 'Could not load voice list: ', '共 ': '', ' 个音色': ' voices', '合成中…': 'Synthesizing…', '试听完成': 'Preview complete', '失败': 'Failed',
  '未开始': 'Not started', '正在建立识别链路…': 'Establishing recognition link…', '识别链路准备超时': 'Recognition link timed out', '会话进行中': 'Session in progress', '启动失败': 'Start failed', '已停止': 'Stopped', '正在收尾…': 'Finishing…', '本轮转写已完成，播放已停止': 'This transcription is complete; playback stopped', '识别服务短暂波动 · 正在自动恢复': 'Recognition service is briefly unstable · recovering automatically',
  '音频文件测试': 'Audio file test', '自动流转': 'Auto-advance', '检测到停顿，': 'Pause detected, ', ' 秒后自动结束并进入多人分离…': ' seconds until auto-finish and multi-speaker separation…',
  '还没有记录到内容，再讲一点吧。': 'Nothing has been recorded yet. Tell me a little more.', '暂时没有听清讲述，请靠近麦克风重试，或用文字记录。': 'I could not make out the story. Move closer to the microphone, retry, or use text.', '暂时没有识别到文字。可以重试录音，或改用文字留下这段讲述。': 'No words were recognized. Retry the recording or leave this story as text.', '当前连接设置已更新，讲述与手记已保留。': 'Connection settings updated. Your story and note are saved.', '连接设置已更新，讲述与手记已保留。': 'Connection settings updated. Your story and note are saved.',
  '本地服务未连接或连接配置无效。请检查服务是否启动，刷新页面可重新连接。': 'The local service is unavailable or misconfigured. Check that it is running, then refresh the page.',
}

const ZH = new Map(Object.entries(EN).map(([zh, en]) => [en, zh]))

export function currentLocale() { return store.locale }
export function setLocale(value) {
  store.locale = value === 'en' ? 'en' : 'zh'
  localStorage.setItem('amphion_locale', store.locale)
  document.documentElement.lang = store.locale === 'en' ? 'en' : 'zh-CN'
  document.title = store.locale === 'en' ? 'demo1 · Conversation with 2036' : 'demo1 · 和 2036 对话'
  window.dispatchEvent(new CustomEvent('amphion-locale-change', { detail: store.locale }))
}
export function toggleLocale() { setLocale(store.locale === 'en' ? 'zh' : 'en') }
export function tr(value) {
  if (value == null || typeof value !== 'string') return value
  if (store.locale === 'en') {
    if (EN[value]) return EN[value]
    let match = value.match(/^(\d+) 秒后开始整理，继续说话可接着记录。$/)
    if (match) return `${match[1]} seconds until we shape the note. Keep speaking to continue.`
    match = value.match(/^检测到停顿，(\d+) 秒后自动结束并进入多人分离…$/)
    if (match) return `Pause detected, auto-finishing in ${match[1]} seconds and moving to speaker separation…`
    match = value.match(/^已配置 (.+)（待生成验证）$/)
    if (match) return `Configured ${match[1]} (generation pending)`
    match = value.match(/^(.+) 已就绪；当前 (\d+)\/(\d+) 个临时会话。音色相似度需本人录音试听。$/)
    if (match) return `${match[1]} ready; ${match[2]}/${match[3]} temporary sessions. Voice similarity requires a personal recording preview.`
    match = value.match(/^共 (\d+) 个音色$/)
    if (match) return `${match[1]} voice${match[1] === '1' ? '' : 's'}`
    match = value.match(/^累计时长 (\d+(?:\.\d+)?) 秒$/)
    if (match) return `Total duration ${match[1]}s`
    match = value.match(/^(\d+) 段$/)
    if (match) return `${match[1]} clip${match[1] === '1' ? '' : 's'}`
    match = value.match(/^(\d+) 个$/)
    if (match) return `${match[1]} profile${match[1] === '1' ? '' : 's'}`
    match = value.match(/^已录 ([\d.]+)s · (.+)KB WAV · 可注册$/)
    if (match) return `Recorded ${match[1]}s · ${match[2]}KB WAV · ready to register`
    match = value.match(/^文件 (.+) · ([\d.]+)s · (.+)KB$/)
    if (match) return `File ${match[1]} · ${match[2]}s · ${match[3]}KB`
    return value
  }
  return ZH.get(value) || value
}
export const t = tr

function translateNode(node) {
  if (!node || node.nodeType !== Node.TEXT_NODE || !node.parentElement) return
  const parent = node.parentElement
  if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName) || parent.isContentEditable) return
  const raw = node.nodeValue
  const trimmed = raw.trim()
  if (!trimmed) return
  const next = tr(trimmed)
  if (next !== trimmed) node.nodeValue = raw.replace(trimmed, next)
}
function translateAttributes(element) {
  for (const name of ['placeholder', 'title', 'aria-label', 'alt']) {
    if (element.hasAttribute(name)) {
      const value = element.getAttribute(name)
      const next = tr(value)
      if (next !== value) element.setAttribute(name, next)
    }
  }
}
export function translateDocument() {
  document.documentElement.lang = store.locale === 'en' ? 'en' : 'zh-CN'
  document.title = store.locale === 'en' ? 'demo1 · Conversation with 2036' : 'demo1 · 和 2036 对话'
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) translateNode(walker.currentNode)
  document.querySelectorAll('[placeholder],[title],[aria-label],[alt]').forEach(translateAttributes)
}
export function installLocaleObserver() {
  const run = () => requestAnimationFrame(() => translateDocument())
  const observer = new MutationObserver(run)
  observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label', 'alt'] })
  window.addEventListener('amphion-locale-change', run)
  translateDocument()
  return () => { observer.disconnect(); window.removeEventListener('amphion-locale-change', run) }
}
