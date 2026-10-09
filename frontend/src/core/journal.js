/* 手记生成与语音修改指令解析（规则式，无 LLM 依赖）
   数据结构对齐设计稿 05/06/07 屏：
   journal = { masthead, title, titleChanged, discoveries[2], quote, added|null, keywords[] } */

const KW_DICT = ['机器人', '无人机', 'AI', '人工智能', '芯片', '脑机', '新能源', '自动驾驶',
  '机器人手臂', '外骨骼', '卫星', '量子', '日常', '生活', '惊喜', '方便', '未来', '养老', '医疗']

const TITLE_STYLES = {
  normal: [
    t => `未来，开始照顾${t}`,
    t => `${t}，悄悄来了`,
    t => `未来，落在${t}`,
  ],
  light: [
    t => `未来，也会搭把手`,
    t => `未来，来${t}串门了`,
    t => `嘿，${t}有点酷`,
  ],
}

function topicOf(text) {
  const hit = ['日常', '生活', '小事'].find(k => text.includes(k))
  if (hit) return '日常'
  const kw = KW_DICT.find(k => text.includes(k))
  return kw || '未来'
}

function sentences(text) {
  return String(text || '')
    .replace(/\s+/g, ' ')
    .split(/[。！？!?\n]+/)
    .map(s => s.trim())
    .filter(s => s.length >= 4)
}

function clamp(s, n = 20) {
  s = s.replace(/^[，、,.\s]+/, '')
  return s.length <= n ? s : s.slice(0, n - 1) + '…'
}

/* 讲述全文 -> 手记。支持分段输入（三问连讲）：
   传数组时发现 = 每问第一条陈述句（≤3 条）；传字符串时维持原「前两条」逻辑。
   原话 = 全文末句 / 关键词 3 个 / 标题模板 */
export function buildJournal(input) {
  const segs = (Array.isArray(input) ? input : [input])
    .map(s => String(s || '').trim()).filter(Boolean)
  const text = segs.join('\n')
  const findings = (segs.length > 1
    ? segs.map(s => sentences(s)[0]).filter(Boolean)
    : sentences(text).slice(0, 2)
  ).map(s => clamp(s)).slice(0, 3)
  const quote = clamp(sentences(text).slice(-1)[0] || text.slice(0, 20))
  const kws = KW_DICT.filter(k => text.includes(k)).slice(0, 3)
  while (kws.length < 3) kws.push(['未来', '日常', '惊喜'][kws.length] || '未来')
  const topic = topicOf(text)
  const title = TITLE_STYLES.normal[0](topic)
  return {
    masthead: '我的高交会手记',
    title, titleChanged: false,
    discoveries: findings.length ? findings : ['想到什么说什么'],
    quote, quoteLabel: '留下一句原话',
    added: null,
    keywords: kws.slice(0, 3),
  }
}

/* 修改指令 -> 应用到手记；返回 { journal, changes:[{where,label}] }
   支持：标题改轻松点 / 标题改成“xxx” / 加一句xxx / （未识别 -> null） */
export function applyEdit(journal, utterance) {
  const u = (utterance || '').replace(/\s+/g, '')
  const out = JSON.parse(JSON.stringify(journal))
  const changes = []
  const mTitle = u.match(/标题(?:改成?|换成?|改为?)["“'「『]?(.+?)["”'」』]?$/)
  const mAdd = u.match(/(?:加|添|补充|再加)一?(?:句|条|段)(?:话)?["“'「『]?(.+?)["”'」』]?$/)
  if (/标题.*(轻松|活泼|简单|俏皮|口语)/.test(u) || (mTitle && /轻松|活泼/.test(u))) {
    const topic = topicOf([journal.quote, ...journal.discoveries].join(''))   // 主题取自手记内容而非指令
    out.title = TITLE_STYLES.light[Math.floor(Math.random() * TITLE_STYLES.light.length)](topic)
    out.titleChanged = true
    changes.push({ where: 'title', label: '标题已修改' })
  } else if (mTitle) {
    out.title = clamp(mTitle[1], 16)
    out.titleChanged = true
    changes.push({ where: 'title', label: '标题已修改' })
  }
  if (mAdd) {
    out.added = { text: clamp(mAdd[1].replace(/["”'」』]/g, ''), 24), isNew: true }
    changes.push({ where: 'added', label: '新增' })
  }
  if (!changes.length) return null
  return { journal: out, changes }
}
