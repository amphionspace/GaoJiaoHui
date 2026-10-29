<script setup>
import { computed } from 'vue'
import { store } from '../core/store.js'
const props = defineProps({ journal: { type: Object, required: true }, imageError: { type: String, default: '' }, imageBusy: Boolean })
defineEmits(['retry-image'])
const noteText = computed(() => props.journal.noteText || props.journal.summary || '')
</script>

<template>
  <article class="journey-receipt" :aria-label="store.locale === 'en' ? 'A Letter to 2036 keepsake' : '给未来的信便签'">
    <!-- Fixed stationery contains no example landscape. Both preview and print use this component. -->
    <img class="receipt-template" src="/journey/receipt/letter-template-no-lines.png" alt="安菲翁科技 · 给未来的信 · A Letter to 2036" />
    <section class="receipt-note-area" aria-label="给未来的信正文">
      <p v-if="noteText" class="receipt-note-text">{{ noteText }}</p>
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
.journey-receipt{position:relative;isolation:isolate;container-type:inline-size;box-sizing:border-box;width:100%;aspect-ratio:941/1672;margin:0 auto;padding:0;overflow:hidden;background:#f4ebdf;color:#493f32;box-shadow:0 12px 40px #655c4b18}
.receipt-template{position:absolute;inset:0;display:block;width:100%;height:100%;max-width:none;object-fit:fill;pointer-events:none}
.receipt-note-area{position:absolute;left:10.8%;top:34%;width:78.4%;height:27%;display:flex;align-items:center;justify-content:center;margin:0;padding:0;overflow:hidden}
.receipt-note-text,.receipt-note-pending{margin:0!important;padding:0!important;font-family:'Receipt Hand','Songti SC',serif;font-weight:400;color:#284c3b;letter-spacing:0;overflow-wrap:anywhere;white-space:pre-wrap;font-size:3.9cqw!important;line-height:1.9!important;text-align:center;text-wrap:pretty}
.receipt-note-pending{color:#8a7e68;text-align:center;font-size:2.6cqw!important}
.receipt-sketch-area{position:absolute;left:5.5%;bottom:10%;width:89%;height:27%;margin:0;padding:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
.receipt-sketch-area img{display:block;width:100%;height:100%;object-fit:contain;mask-image:linear-gradient(to right,transparent,#000 4%,#000 96%,transparent),linear-gradient(to bottom,transparent,#000 7%,#000 94%,transparent);mask-composite:intersect;}
.receipt-sketch-area figcaption{font-size:2.8cqw;color:#75644e;text-align:center;line-height:1.7;padding:0 8%}
.receipt-sketch-area button{display:block;margin:10px auto 0;background:transparent;color:inherit;border:1px solid currentColor;border-radius:5px;padding:6px 12px;font:inherit}
@media print{.receipt-sketch-area figcaption{display:none}}
@media print{.journey-receipt{width:101.6mm;height:152.4mm;aspect-ratio:auto;flex:none;max-width:none;box-shadow:none;break-inside:avoid;print-color-adjust:exact;-webkit-print-color-adjust:exact}.receipt-note-text{font-size:8pt!important;line-height:1.9!important}.receipt-note-pending,.receipt-sketch-area figcaption{font-size:6.5pt!important}}
</style>
