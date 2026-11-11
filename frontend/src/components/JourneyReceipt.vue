<script setup>
import { computed } from 'vue'
import { store } from '../core/store.js'
import { receiptParagraphs } from '../core/receiptLayout.js'
const props = defineProps({ journal: { type: Object, required: true }, imageError: { type: String, default: '' }, imageBusy: Boolean })
defineEmits(['retry-image'])
const noteText = computed(() => props.journal.noteText || props.journal.summary || '')
const noteParagraphs = computed(() => receiptParagraphs(noteText.value, store.locale))
const manyClauses = computed(() => noteParagraphs.value.reduce((count, paragraph) => count + paragraph.length, 0) >= 8)
</script>

<template>
  <article class="journey-receipt" :aria-label="store.locale === 'en' ? 'A Letter to 2036 keepsake' : '给未来的信便签'">
    <!-- Preserve the lettering's proportions; only the blank middle of the paper stretches. -->
    <div class="receipt-template" role="img" aria-label="安菲翁科技 · 给未来的信 · A Letter to 2036">
      <span class="receipt-paper-top">
        <img src="/journey/receipt/letter-template-no-lines.png" alt="" />
        <img class="receipt-title-stretch" src="/journey/receipt/letter-title.png" alt="" />
      </span>
      <span class="receipt-paper-middle"><img src="/journey/receipt/letter-template-no-lines.png" alt="" /></span>
      <span class="receipt-paper-bottom"><img src="/journey/receipt/letter-template-no-lines.png" alt="" /></span>
    </div>
    <section class="receipt-note-area" aria-label="给未来的信正文">
      <p v-if="noteText" class="receipt-note-text" :class="{ 'receipt-note-dense': manyClauses }"><template v-for="(paragraph, paragraphIndex) in noteParagraphs" :key="paragraphIndex"><br v-if="paragraphIndex" /><span v-for="(phrase, phraseIndex) in paragraph" :key="phraseIndex" class="receipt-note-phrase"><span v-for="(word, wordIndex) in phrase.words" :key="wordIndex" class="receipt-note-word">{{ word }}</span></span></template></p>
      <p v-else class="receipt-note-pending">讲述已留存，等待整理</p>
    </section>
    <figure class="receipt-sketch-area">
      <img v-if="journal.sketch" :src="journal.sketch" :alt="store.locale === 'en' ? 'An illustration of your words' : '根据你的讲述生成的插画'" />
      <figcaption v-else role="status">
        {{ imageBusy ? '正在生成你的插画…' : imageError || (noteText ? '本次插画尚未生成' : '回信完成后将生成插画') }}
        <button v-if="noteText && !imageBusy" type="button" @click="$emit('retry-image')">重试插画</button>
      </figcaption>
    </figure>
  </article>
</template>

<style scoped>
@font-face{font-family:'Receipt Hand';src:url('/journey/fonts/zcool-xiaowei.woff2') format('woff2');font-weight:400;font-display:swap}
.journey-receipt{position:relative;isolation:isolate;container-type:inline-size;box-sizing:border-box;width:100%;aspect-ratio:80/170;margin:0 auto;padding:0;overflow:hidden;background:#f4ebdf;color:#493f32;box-shadow:0 12px 40px #655c4b18}
/* The 941 x 1672 source has a 520px header, 1082px blank middle and 70px footer. */
.receipt-template{--paper-top:calc(100cqw * 520 / 941);--paper-bottom:calc(100cqw * 70 / 941);position:absolute;inset:0;pointer-events:none}
.receipt-template>span{position:absolute;left:0;width:100%;overflow:hidden}
.receipt-template img{position:absolute;left:0;display:block;width:100%;height:auto;max-width:none}
.receipt-paper-top{top:0;height:var(--paper-top)}
.receipt-paper-top img{top:0}
.receipt-paper-top .receipt-title-stretch{top:calc(100cqw * 220 / 941);left:calc(50% - (100cqw * 555 / 941 * 1.2 / 2));width:calc(100cqw * 555 / 941 * 1.2);height:calc(100cqw * 130 / 941);object-fit:fill;z-index:1}
.receipt-paper-middle{top:var(--paper-top);bottom:var(--paper-bottom)}
.receipt-paper-middle img{top:calc(-100% * 520 / 1082);height:calc(100% * 1672 / 1082)}
.receipt-paper-bottom{bottom:0;height:var(--paper-bottom)}
.receipt-paper-bottom img{bottom:0}
.receipt-note-area{position:absolute;left:10.8%;top:34%;width:78.4%;height:27%;display:flex;align-items:center;justify-content:center;margin:0;padding:0}
.receipt-note-text,.receipt-note-pending{margin:0!important;padding:0!important;font-family:'Receipt Hand','Songti SC',serif;font-weight:400;color:#284c3b;letter-spacing:0;overflow-wrap:anywhere;white-space:pre-wrap;font-size:4.7625cqw!important;line-height:1.9!important;text-align:center;text-wrap:pretty}
.receipt-note-pending{color:#8a7e68;text-align:center;font-size:2.6cqw!important}
/* Keep a clause together when it fits; longer clauses wrap between complete words. */
.receipt-note-text{width:100%;white-space:normal;overflow-wrap:normal;text-wrap:wrap;line-break:strict;transform:translateY(min(0px,calc((57.375cqw - 100%) / 2)))}
/* At 80 x 170 mm the usual text area is 57.375cqw high. Extra lines extend
   upward into the blank paper, keeping the bottom clear of the illustration. */
.receipt-note-phrase,.receipt-note-word{display:inline-block;max-width:100%;vertical-align:top}
.receipt-note-word{white-space:pre-wrap;overflow-wrap:anywhere}
/* Many short clauses need tighter leading to stay clear of the printed header. */
.receipt-note-text.receipt-note-dense{line-height:1.65!important}
.receipt-sketch-area{position:absolute;left:5.5%;bottom:10%;width:89%;height:27%;margin:0;padding:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
.receipt-sketch-area img{display:block;width:100%;height:100%;object-fit:contain;mask-image:linear-gradient(to right,transparent,#000 4%,#000 96%,transparent),linear-gradient(to bottom,transparent,#000 7%,#000 94%,transparent);mask-composite:intersect;}
.receipt-sketch-area figcaption{font-size:2.8cqw;color:#75644e;text-align:center;line-height:1.7;padding:0 8%}
.receipt-sketch-area button{display:block;margin:10px auto 0;background:transparent;color:inherit;border:1px solid currentColor;border-radius:5px;padding:6px 12px;font:inherit}
@media print{.receipt-sketch-area figcaption{display:none}}
@media print{.journey-receipt{width:80mm;height:170mm;aspect-ratio:auto;flex:none;max-width:none;box-shadow:none;break-inside:avoid;print-color-adjust:exact;-webkit-print-color-adjust:exact}.receipt-note-text{font-size:10.8pt!important;line-height:1.9!important}.receipt-note-pending,.receipt-sketch-area figcaption{font-size:6.5pt!important}}
</style>
