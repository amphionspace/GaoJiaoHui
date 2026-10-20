import test from 'node:test'
import assert from 'node:assert/strict'
import { detectTopic, endingIntent, previewIntent, createJourneyJournal, editJourneyJournal, composeJourneyJournal, greetingPeriod, cleanSpokenText } from '../src/core/journey.js'

test('natural topic selection preserves the product sentence as journal content', () => {
  const firstSentence = '我今天看到最惊喜的产品是一个会做咖啡的机器人'
  assert.equal(detectTopic(firstSentence), 'product')
  const journal = createJourneyJournal(firstSentence, 'product')
  assert.equal(journal.sourceText, firstSentence)
  assert.equal(journal.originalText, firstSentence)
  assert.equal(journal.illustration, 'robot')
})

test('an explicit idea about a robot is an idea, not a product selection', () => {
  assert.equal(detectTopic('我突然有个想法，让机器人帮老人搬东西'), 'idea')
  assert.equal(detectTopic('我想讲个故事，今天有个机器人陪我聊天'), 'story')
  assert.equal(detectTopic('嗯，让我想一想'), null)
})

test('ending intent requires a closing clause and removes it from the journal', () => {
  assert.equal(endingIntent('等我说完了再回答'), null)
  assert.equal(endingIntent('我还没说完'), null)
  assert.equal(endingIntent('他说“我说完了”'), null)
  assert.equal(endingIntent('刚才看到一架无人机。我说完了。').text, '刚才看到一架无人机')
  const journal = createJourneyJournal('刚才看到一架无人机。我说完了。', 'product')
  assert.equal(journal.sourceText, '刚才看到一架无人机')
  assert.equal(journal.illustration, 'space')
  assert.throws(() => createJourneyJournal('我说完了', 'story'))
})

test('preview commands do not trigger print from quoted or negated content', () => {
  assert.equal(previewIntent('不要帮我打印'), null)
  assert.equal(previewIntent('我说的不是帮我打印'), null)
  assert.equal(previewIntent('请帮我打印。').type, 'print')
  assert.equal(previewIntent('再听一遍').type, 'replay')
  assert.equal(previewIntent('继续说').type, 'continue')
})

test('adding content preserves the entire addition and invalidates the previous letter', () => {
  const journal = createJourneyJournal('今天遇到一位很热情的志愿者。', 'story')
  journal.messageToSelf = '之前生成的回信'
  journal.generation = 'model'
  const addition = '明年还想来，我想带上爸爸，让他看看现在的机器人如何帮他搬运东西，这比一场展览对我更重要。'
  const updated = editJourneyJournal(journal, '加一句' + addition)
  assert.equal(updated.revision, 1)
  assert.equal(updated.messageToSelf, '')
  assert.equal(updated.generation, 'pending')
  assert.ok(updated.originalText.endsWith(addition))
  assert.ok(updated.sourceText.endsWith(addition))
  assert.equal(journal.revision, 0)
  assert.equal(editJourneyJournal(journal, '随便改一下'), null)
})

test('an ungenerated draft never disguises a template or first-sentence excerpt as a letter', () => {
  const source = '我今天看到机器人。起初只觉得新奇。后来想到爸爸搬东西很吃力，我想弄清它能不能帮到他。'
  const journal = createJourneyJournal(source, 'product')
  assert.equal(journal.messageToSelf, '')
  assert.equal(journal.summary, '')
  assert.equal(journal.sourceText, source)
  assert.equal(journal.generation, 'pending')
  assert.deepEqual(journal.keywords, [])
})

test('the reported transcript loses fillers without producing a broken or invented theme', () => {
  const raw = '今天的测试是，呃，关于未来的灵感'
  assert.equal(cleanSpokenText(raw), '今天的测试是，关于未来的灵感')
  const journal = createJourneyJournal(raw, 'idea')
  assert.equal(journal.originalText, raw)
  assert.doesNotMatch(journal.sourceText, /呃/)
  assert.equal(journal.messageToSelf, '')
})

test('cleanup preserves time order, substantive words, and complete sentence subjects', () => {
  assert.equal(cleanSpokenText('嗯，呃，那个，今天帮爸爸买了额温枪。然后，我们去看了机器人。'), '今天帮爸爸买了额温枪。然后，我们去看了机器人。')
  const idea = createJourneyJournal('我突然有个想法，让机器人帮老人搬东西', 'idea')
  assert.match(idea.sourceText, /让机器人帮老人搬东西/)
  const story = createJourneyJournal('今天的经历让我有点难过，我需要休息一下。', 'story')
  assert.match(story.sourceText, /今天的经历/)
  assert.doesNotMatch(story.sourceText, /温度|美好|惊喜/)
})

test('generation uses the full raw transcript and keeps model summary separate from the spoken reply', async () => {
  const raw = '嗯，我看到机器人。' + '一开始我觉得挺新鲜的。'.repeat(30) + '不过真正让我在意的是爸爸能不能少搬一些重物。我说完了。'
  const draft = createJourneyJournal(raw, 'product')
  let payload
  const result = await composeJourneyJournal(draft, { request: async (url, options) => {
    assert.equal(url, '/api/journey/compose')
    payload = JSON.parse(options.body)
    return { ok: true, json: async () => ({ generation: 'model', summary: '我想知道机器人能否替爸爸搬重物。', message: '我是以后的你。你看到机器人的时候，想起的是爸爸搬重物的辛苦。', keywords: ['爸爸', '搬重物'], model: 'test-model' }) }
  } })
  assert.equal(payload.transcript, raw)
  assert.equal(result.originalText, raw)
  assert.match(result.summary, /爸爸/)
  assert.notEqual(result.summary, result.messageToSelf)
  assert.equal(draft.messageToSelf, '')
  const renamed = editJourneyJournal(result, '标题改成想让爸爸轻松一点')
  assert.equal(renamed.messageToSelf, result.messageToSelf)
  assert.equal(renamed.generation, 'model')
})

test('unavailable or malformed text responses preserve the draft without template substitution', async () => {
  const draft = createJourneyJournal('呃我想让爸爸轻松一点。', 'idea')
  for (const response of [
    { ok: false, json: async () => ({ detail: { message: '回信服务尚未连接' } }) },
    { ok: true, json: async () => ({ generation: 'model', summary: '内容', keywords: [] }) },
  ]) await assert.rejects(composeJourneyJournal(draft, { request: async () => response }))
  assert.equal(draft.messageToSelf, '')
  assert.equal(draft.originalText, '呃我想让爸爸轻松一点。')
  assert.equal(draft.sourceText, '我想让爸爸轻松一点。')
})

test('greeting uses all four time periods with explicit boundaries', () => {
  assert.equal(greetingPeriod(9).id, 'morning')
  assert.equal(greetingPeriod(11).id, 'noon')
  assert.equal(greetingPeriod(14).id, 'afternoon')
  assert.equal(greetingPeriod(18).id, 'evening')
})

test('overlong replies from an outdated server are rejected without truncating or changing the original', async () => {
  const draft = createJourneyJournal('我想让爸爸搬东西省些力。', 'future')
  const boundary = '字'.repeat(49) + '。'
  const requestFor = message => async () => ({ ok: true, json: async () => ({
    generation: 'model', summary: '我希望爸爸搬东西能省些力。', message, keywords: ['爸爸'],
  }) })
  const result = await composeJourneyJournal(draft, { request: requestFor(boundary) })
  assert.equal(result.messageToSelf, boundary)
  await assert.rejects(composeJourneyJournal(draft, { request: requestFor(boundary + '呀') }), /回信太长/)
  assert.equal(draft.messageToSelf, '')
  assert.equal(draft.originalText, '我想让爸爸搬东西省些力。')
})
