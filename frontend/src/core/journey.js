export const TOPICS = [
  { id: 'product', number: '01', title: '最惊喜的产品', subtitle: '让你眼前一亮的科技', prompt: '我今天看到最惊喜的产品是……', color: 'mint' },
  { id: 'idea', number: '02', title: '一个新想法', subtitle: '关于未来的灵感', prompt: '我突然有个想法……', color: 'blue' },
  { id: 'story', number: '03', title: '今天的故事', subtitle: '在这里遇见的美好', prompt: '今天发生了一件事……', color: 'yellow' },
]

export function greetingPeriod(hour = new Date().getHours()) {
  if (hour < 11) return { id: 'morning', text: '上午好' }
  if (hour < 14) return { id: 'noon', text: '中午好' }
  if (hour < 18) return { id: 'afternoon', text: '下午好' }
  return { id: 'evening', text: '晚上好' }
}

const normalize = text => String(text || '').replace(/[\s，。！？、,.!?：:；;]/g, '')
export function detectTopic(text) {
  const t = normalize(text)
  if (/我(?:突然)?(?:有|想到|想出).{0,5}(?:想法|点子|主意)|一个新想法|如果.{1,45}(?:就好了|能不能)|我希望未来/.test(t)) return 'idea'
  if (/我想(?:讲|说|聊).{0,4}(?:故事|件事)|今天(?:发生|遇到|遇见).{0,5}(?:事|人)|今天的故事/.test(t)) return 'story'
  if (/产品|科技|技术|机器人|无人机|芯片|外骨骼|最.{0,3}惊喜|眼前一亮/.test(t)) return 'product'
  if (/想法|灵感|点子|希望|如果/.test(t)) return 'idea'
  if (/故事|遇见|遇到|刚刚|小事/.test(t)) return 'story'
  return null
}

// Only a standalone closing clause ends a turn, never a quotation or a negation.
export function endingIntent(text) {
  const source = String(text || '').trim()
  const match = source.match(/(?:^|[，。！？,.!?\n]\s*)(?:好了[，,]?\s*)?(我说完了|我讲完了|就这些|讲完了)[。！!\s]*$/)
  if (!match) return null
  return { text: source.slice(0, match.index).trim(), command: match[1] }
}

export function previewIntent(text) {
  const t = normalize(text)
  if (/^(?:请|麻烦)?(?:帮我)?(?:打印|打印吧|打印出来|打印手记|确认打印|就这样打印)$/.test(t)) return { type: 'print' }
  if (/^(?:请)?(?:再听一遍|再播一遍|重新播放|重播)$/.test(t)) return { type: 'replay' }
  if (/^(?:我想)?(?:继续说|再补充一点|继续讲述)$/.test(t)) return { type: 'continue' }
  if (/^(?:标题|加一句|补充一句|再加一句)/.test(t)) return { type: 'edit', text: String(text).trim() }
  return null
}

export function cleanSpokenText(text) {
  return String(text || '')
    .replace(/[呃嗯]+[，,\s]*/gu, '')
    .replace(/\s+/g, ' ')
    .replace(/(^|[，。！？、,.!?；;：:“「\s])(?:呃+|额+|嗯+|那个|这个|就是)(?=[，。！？、,.!?；;：:”」\s]|$)/gu, '$1')
    .replace(/([，、])\s*(?=[，、。！？!?])/g, '')
    .replace(/\s+([，。！？、,.!?；;：:])/g, '$1')
    .replace(/([，、]){2,}/g, '$1')
    .replace(/^[，、,\s]+|[，、,\s]+$/g, '')
    .trim()
}

export function createJourneyJournal(text, topicId, now = new Date(), language = 'zh') {
  const original = String(text || '')
  const clean = cleanSpokenText(endingIntent(original)?.text ?? original)
  if (!clean) throw new Error('还没有记录到内容，再讲一点吧。')
  const illustration = /机器人/.test(clean) ? 'robot' : /咖啡/.test(clean) ? 'coffee' : /无人机|飞行|卫星|航天/.test(clean) ? 'space' : topicId
  return {
    title: language === 'en'
      ? (topicId === 'future' ? 'What I Hope for in 2036' : topicId === 'idea' ? 'The Future Starts with This Idea' : topicId === 'story' ? 'Keeping Today for Tomorrow' : 'Today, I Met the Future')
      : (topicId === 'future' ? '我期待的 2036' : topicId === 'idea' ? '未来，从这个想法开始' : topicId === 'story' ? '把今天，留给未来' : '今天，我遇见了未来'),
    summary: '', messageToSelf: '', takeaway: '', keywords: [], generation: 'pending',
    sourceText: clean, originalText: original, topicId, illustration,
    date: now.toLocaleDateString(language === 'en' ? 'en-CA' : 'zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }),
    number: `${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}-${String(Math.floor(Math.random() * 10000)).padStart(4, '0')}`,
    revision: 0,
  }
}

export function editJourneyJournal(journal, instruction) {
  const title = instruction.trim().match(/^标题改成[：:\s]*(.+)$/s)
  if (title) return { ...journal, title: cleanSpokenText(title[1]), revision: journal.revision + 1 }
  const addition = instruction.trim().match(/^(?:再加一句|补充一句|加一句)[：:\s]*(.+)$/s)
  if (!addition) return null
  const originalText = `${journal.originalText}\n补充：${addition[1]}`
  return { ...journal, originalText, sourceText: `${journal.sourceText}\n${cleanSpokenText(addition[1])}`,
    summary: '', messageToSelf: '', takeaway: '', keywords: [], generation: 'pending', revision: journal.revision + 1 }
}

export async function composeJourneyJournal(journal, { signal, apiKey = '', request = fetch, language = 'zh' } = {}) {
  // Send the complete ASR record, including later corrections and additions.
  const response = await request('/api/journey/compose', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(90000)]) : AbortSignal.timeout(90000),
    body: JSON.stringify({ transcript: journal.originalText, topic: journal.topicId, language }),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || '回信暂时无法生成，完整讲述已保留。')
  const noteText = data.note_text || data.summary
  if (data.generation !== 'model' || !noteText?.trim() || !data.message?.trim() || !Array.isArray(data.keywords)) {
    throw new Error('回信内容不完整，完整讲述已保留，请重新整理。')
  }
  if (Array.from(data.message).length > 50) {
    throw new Error('这次回信太长，完整讲述已保留，请重新整理。')
  }
  return { ...journal, noteText, summary: noteText, messageToSelf: data.message, takeaway: data.takeaway || '', keywords: data.keywords,
    generation: 'model', textModel: data.model, sketchPrompt: data.sketch_prompt || '' }
}

export async function illustrateJourneyJournal(journal, { signal, apiKey = '', request = fetch } = {}) {
  const response = await request('/api/journey/illustrate', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(105000)]) : AbortSignal.timeout(105000),
    body: JSON.stringify({ summary: journal.summary, scene: journal.sketchPrompt || journal.summary }),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '插画暂时未能生成，可以重试或打印文字手记。')
  if (!/^data:image\/png;base64,[A-Za-z0-9+/]+=*$/.test(data.image || '')) throw new Error('未收到有效插画，请重试。')
  return { sketch: data.image, imageModel: data.model }
}
