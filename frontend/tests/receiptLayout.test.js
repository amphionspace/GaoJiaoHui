import test from 'node:test'
import assert from 'node:assert/strict'
import { receiptParagraphs } from '../src/core/receiptLayout.js'

const texts = paragraphs => paragraphs.map(paragraph => paragraph.map(phrase => phrase.text))
function assertPreserved(input, paragraphs = receiptParagraphs(input)) {
  assert.deepEqual(paragraphs.map(paragraph => paragraph.map(phrase => phrase.text).join('')), input.split(/\r\n|\r|\n/u))
  for (const paragraph of paragraphs) for (const phrase of paragraph) assert.equal(phrase.words.join(''), phrase.text)
  return paragraphs
}

test('keeps the complete negation together after a semantic comma boundary', () => {
  const text = '我预见十年后的世界是和平的，没有战争。'
  const paragraphs = assertPreserved(text)
  assert.deepEqual(texts(paragraphs), [['我预见十年后的世界是和平的，', '没有战争。']])
  assert.ok(paragraphs[0][1].words.every(word => !/^[，。]/u.test(word)))
})

test('preserves existing paragraphs, empty lines, whitespace and unpunctuated endings', () => {
  const text = '  和家人慢慢走。 \r\n\r\n仍然有时间\n'
  const paragraphs = assertPreserved(text)
  assert.deepEqual(texts(paragraphs), [['  和家人慢慢走。 '], [], ['仍然有时间'], []])
  assert.deepEqual(receiptParagraphs(''), [[]])
})

test('attaches closing quotes and brackets to the preceding phrase', () => {
  const text = '我想：“没有战争！”（也没有饥饿。）；我们一起走。'
  const paragraphs = assertPreserved(text)
  assert.deepEqual(texts(paragraphs), [['我想：', '“没有战争！”', '（也没有饥饿。）；', '我们一起走。']])
  assert.ok(paragraphs[0][1].words[0].startsWith('“'))
  assert.ok(paragraphs[0][1].words.at(-1).endsWith('！”'))
  assert.ok(paragraphs[0][2].words[0].startsWith('（'))
})

test('handles punctuation runs without adding or losing punctuation', () => {
  const text = '真的吗？！愿意……也许——可以；慢慢来：一起走'
  const paragraphs = assertPreserved(text)
  assert.deepEqual(texts(paragraphs), [['真的吗？！', '愿意……也许——可以；', '慢慢来：', '一起走']])
})

test('preserves mixed-language numbers, times and URL punctuation', () => {
  const text = '2036年10:30，价格1,000.50和3.14，见https://example.com/a?x=1,000&t=10:30；8：17再见。'
  const paragraphs = assertPreserved(text)
  assert.deepEqual(texts(paragraphs), [['2036年10:30，', '价格1,000.50和3.14，', '见https://example.com/a?x=1,000&t=10:30；', '8：17再见。']])
})

test('uses English punctuation boundaries only before whitespace or at the end', () => {
  const text = 'I hope, "there is peace!" Visit example.com; then come home: no war.'
  const paragraphs = assertPreserved(text, receiptParagraphs(text, 'en'))
  assert.deepEqual(texts(paragraphs), [['I hope, ', '"there is peace!" ', 'Visit example.com; ', 'then come home: ', 'no war.']])
  const quote = paragraphs[0][1]
  assert.ok(quote.words[0].startsWith('"'))
  assert.ok(quote.words.at(-1).endsWith('!" '))
})

test('keeps emoji sequences and long words intact without a segmenter', () => {
  const descriptor = Object.getOwnPropertyDescriptor(Intl, 'Segmenter')
  Object.defineProperty(Intl, 'Segmenter', { configurable: true, writable: true, value: undefined })
  try {
    const text = '我们👨‍👩‍👧‍👦一起走，向🇨🇳出发👍🏽；café和supercalifragilisticexpialidocious。'
    const paragraphs = assertPreserved(text)
    const words = paragraphs.flatMap(paragraph => paragraph.flatMap(phrase => phrase.words))
    assert.ok(words.includes('👨‍👩‍👧‍👦'))
    assert.ok(words.includes('🇨🇳'))
    assert.ok(words.includes('👍🏽；'))
    assert.ok(words.includes('café'))
    assert.ok(words.includes('supercalifragilisticexpialidocious。'))
  } finally { Object.defineProperty(Intl, 'Segmenter', descriptor) }
})

test('retains every character in long notes and falls back for unsupported locales', () => {
  const text = '我希望不用总为工作赶时间，可以在草地上慢慢走，也可以带家人去看雪山。没有战争，没有必须赶上的最后一班车。'
  assertPreserved(text)
  assertPreserved(text, receiptParagraphs(text, 'not a valid locale'))
})
