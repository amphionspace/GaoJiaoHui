const CHINESE_BREAK = /[，。！？；：]/u
const ASCII_BREAK = /[,.;:!?]/u
const CLOSING = /[)\]}）］｝】》〉」』〕”’]/u
const OPENING = /[(\[{（［｛【《〈「『〔“‘]/u
const PUNCTUATION = /^\p{P}+$/u
const SPACE = /^\s+$/u
const NUMBER = /\p{N}/u

function asciiBoundary(text, index) {
  let next = index + 1
  while (next < text.length && (ASCII_BREAK.test(text[next]) || CHINESE_BREAK.test(text[next]) || CLOSING.test(text[next]) || /["']/u.test(text[next]))) next++
  return next === text.length || /\s/u.test(text[next])
}

function isBoundary(text, index) {
  const char = text[index]
  // Keep decimals, times and grouped numbers intact, including fullwidth separators.
  if (/[.,:，：]/u.test(char) && NUMBER.test(text[index - 1] || '') && NUMBER.test(text[index + 1] || '')) return false
  return CHINESE_BREAK.test(char) || (ASCII_BREAK.test(char) && asciiBoundary(text, index))
}

function phrasesIn(paragraph) {
  const phrases = []
  let start = 0
  for (let index = 0; index < paragraph.length; index++) {
    if (!isBoundary(paragraph, index)) continue
    let end = index + 1
    // A closing quote belongs to the phrase before it, as does a punctuation run.
    while (end < paragraph.length && (CLOSING.test(paragraph[end]) || /["']/u.test(paragraph[end]) || isBoundary(paragraph, end))) end++
    while (end < paragraph.length && /\s/u.test(paragraph[end])) end++
    phrases.push(paragraph.slice(start, end))
    start = end
    index = end - 1
  }
  if (start < paragraph.length) phrases.push(paragraph.slice(start))
  return phrases
}

function fallbackSegments(text) {
  const segments = []
  for (const char of text) {
    const last = segments.at(-1)
    const joinsEmoji = /[\p{Mark}\uFE0E\uFE0F\u{1F3FB}-\u{1F3FF}\u{E0020}-\u{E007F}\u200D]/u.test(char) || last?.endsWith('\u200D')
    const pairsFlag = /\p{Regional_Indicator}/u.test(char) && /^\p{Regional_Indicator}$/u.test(last || '')
    const joinsLatinWord = /^[\p{Script=Latin}\p{N}_]+$/u.test(char) && /^[\p{Script=Latin}\p{N}_]+$/u.test(last || '')
    if (last && (joinsEmoji || pairsFlag || joinsLatinWord)) segments[segments.length - 1] += char
    else segments.push(char)
  }
  return segments.map(segment => ({ segment }))
}

function wordsIn(text, segmenter) {
  const segments = segmenter ? segmenter.segment(text) : fallbackSegments(text)
  const words = []
  let pending = '', offset = 0
  for (const { segment } of segments) {
    const previous = text[offset - 1] || ''
    const straightOpeningQuote = /^["']$/u.test(segment) && (!previous || SPACE.test(previous) || OPENING.test(previous))
    if (OPENING.test(segment) || straightOpeningQuote) pending += segment
    else if (SPACE.test(segment) || PUNCTUATION.test(segment)) {
      if (pending || !words.length) pending += segment
      else words[words.length - 1] += segment
    } else {
      words.push(pending + segment)
      pending = ''
    }
    offset += segment.length
  }
  if (pending) {
    if (words.length) words[words.length - 1] += pending
    else words.push(pending)
  }
  return words
}

// Layout hints only: the original note remains unchanged for storage, speech and copying.
export function receiptParagraphs(text, locale = 'zh') {
  let segmenter
  try { segmenter = new Intl.Segmenter(locale, { granularity: 'word' }) } catch { /* Older browsers use the character-safe fallback. */ }
  return String(text ?? '').split(/\r\n|\r|\n/u).map(paragraph => phrasesIn(paragraph).map(phrase => ({ text: phrase, words: wordsIn(phrase, segmenter) })))
}
