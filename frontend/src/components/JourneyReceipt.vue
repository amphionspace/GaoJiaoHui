<script setup>
import { store } from '../core/store.js'
defineProps({ journal: { type: Object, required: true } })
</script>

<template>
  <article class="journey-receipt" :aria-label="store.locale === 'en' ? 'Conversation with 2036 keepsake' : '和 2036 对话纪念便签'">
    <header class="receipt-masthead">
      <div class="receipt-kicker"><span>高交会 · 安菲翁科技</span><span>私人珍藏版</span></div>
      <strong>和 2036 对话</strong>
      <p lang="en">A Letter to 2036</p>
    </header>
    <div class="receipt-meta"><time>{{ journal.date }}</time><span>NO. {{ journal.number }}</span></div>
    <section class="receipt-story">
      <div class="receipt-section-label"><span>01 / 我的未来想象</span><span lang="en">Today</span></div>
      <h3>{{ journal.title }}</h3>
      <p class="receipt-summary">{{ journal.summary || journal.sourceText }}</p>
    </section>
    <figure v-if="journal.sketch" class="receipt-sketch"><img :src="journal.sketch" :alt="store.locale === 'en' ? `A line drawing of the future: ${journal.summary}` : `未来想象的简笔画：${journal.summary}`" width="1024" height="768" /></figure>
    <div v-if="journal.keywords.length" class="receipt-index">
      <span class="receipt-index-label">这通电话<br />关于</span>
      <p><span v-for="(word, index) in journal.keywords" :key="word"><i>{{ String(index + 1).padStart(2, '0') }}</i>{{ word }}</span></p>
    </div>
    <section v-if="journal.takeaway" class="receipt-reply">
      <div class="receipt-section-label"><span>02 / 来自未来的回音</span><span lang="en">Tomorrow</span></div>
      <blockquote><span class="receipt-quote-mark" aria-hidden="true">“</span><p>{{ journal.takeaway }}</p></blockquote>
      <p class="receipt-signature">以后的我，留给现在的我。</p>
    </section>
    <p v-else-if="!journal.messageToSelf" class="receipt-pending">讲述已留存，等待整理</p>
    <footer class="receipt-footer"><em lang="en">See you in 2036.</em><div><span>从今天出发</span><span>寄给 2036 的自己</span></div></footer>
  </article>
</template>

<style scoped>
/* Newspaper hierarchy is shared by the preview and the printed keepsake. */
.journey-receipt{--r-ink:#30332f;--r-rule:#aeb3a6;width:100%;max-width:420px;margin:0 auto;position:relative;padding:26px 28px 22px;overflow-wrap:anywhere;font-family:'Future Display','Songti SC',serif;background:#fafaf5;color:var(--r-ink);border:1px solid #c8cbbe;box-shadow:0 2px 2px #3e443814,0 18px 40px #3e443814}
.journey-receipt::after{content:'';position:absolute;bottom:-5px;left:0;right:0;height:5px;background:linear-gradient(135deg,#fafaf5 25%,transparent 25%) -5px 0/10px 10px,linear-gradient(225deg,#fafaf5 25%,transparent 25%) -5px 0/10px 10px}
.receipt-kicker{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid var(--r-rule);padding-bottom:12px;margin-bottom:16px;font:9px/1.6 'PingFang SC','Microsoft YaHei',sans-serif;color:#687361}
.receipt-masthead{display:block;text-align:center;background:transparent;border:0;padding:0;box-shadow:none}.receipt-masthead strong{display:block;font-size:44px;line-height:1.3;font-weight:600}.receipt-masthead>p{font-family:'Future Latin',Georgia,serif;font-size:24px;font-style:italic;color:#52634f;margin:5px 0 18px}
.receipt-meta{display:flex;justify-content:space-between;gap:12px;border-top:3px double #747e6d;border-bottom:1px solid var(--r-rule);padding:8px 0;font:10px/1.5 Georgia,serif;color:#646b60}
.receipt-story{padding:22px 0}.receipt-section-label{display:flex;justify-content:space-between;gap:10px;font:9px/1.6 'PingFang SC','Microsoft YaHei',sans-serif;color:#6e7867}.receipt-section-label>span:last-child{font-family:Georgia,serif}
h3{font-family:inherit;font-size:24px;font-weight:600;line-height:1.6;margin:15px 0 18px;text-wrap:balance}.receipt-summary{font-size:18px;line-height:2;margin:0;text-align:left;white-space:pre-wrap;font-weight:400}.receipt-summary::first-letter{float:left;font-size:42px;line-height:1.25;margin:2px 6px 0 0;color:#455d48}
.receipt-index{display:grid;grid-template-columns:62px minmax(0,1fr);gap:16px;border-top:1px solid var(--r-rule);border-bottom:1px solid var(--r-rule);padding:14px 0;font-family:'PingFang SC','Microsoft YaHei',sans-serif}.receipt-index-label{font-size:10px;line-height:1.9;color:#78826f;border-right:1px solid #c2c9bb}.receipt-index p{display:flex;gap:8px 15px;flex-wrap:wrap;align-content:center;margin:0}.receipt-index p>span{font-size:12px;line-height:1.7;color:#42583f}.receipt-index i{font-family:Georgia,serif;font-size:9px;font-style:italic;color:#9b665a;margin-right:5px}
.receipt-reply{padding:23px 0 20px}.receipt-reply blockquote{margin:16px 0 12px;position:relative;padding-left:19px;border-left:2px solid #a96a5e}.receipt-quote-mark{font-family:Georgia,serif;font-size:43px;line-height:1;color:#a96a5e}.receipt-reply blockquote p{font-size:24px;line-height:1.75;font-weight:500;margin:-9px 0 0;color:#435a47;text-wrap:pretty}.receipt-signature{font-size:11px;text-align:right;color:#777b6e;margin:14px 0 0}
.receipt-footer{border-top:3px double #747e6d;padding-top:19px;display:flex;flex-direction:column;align-items:center;gap:9px;color:#65715e}.receipt-footer>em{font:italic 23px/1.3 'Future Latin',Georgia,serif}.receipt-footer>span{font:10px/1.7 'PingFang SC','Microsoft YaHei',sans-serif}.receipt-footer>div{display:flex;justify-content:space-between;width:100%;font-size:9px;border-top:1px solid #c2c9bb;margin-top:8px;padding-top:12px}.receipt-pending{font:12px/1.8 sans-serif;color:#777;padding:20px 0}
@media screen and (orientation:portrait) and (min-width:701px){.journey-receipt{max-width:490px;padding:32px}.receipt-masthead strong{font-size:48px}.receipt-summary{font-size:20px}.receipt-reply blockquote p{font-size:26px}}
@media screen and (orientation:portrait) and (min-width:1800px){
  .journey-receipt{max-width:980px;padding:64px;border-width:2px}.receipt-kicker{font-size:22px;padding-bottom:24px;margin-bottom:32px;gap:20px}.receipt-masthead strong{font-size:96px}.receipt-masthead>p{font-size:48px;margin:10px 0 36px}.receipt-meta{font-size:22px;padding:16px 0;border-top-width:6px;border-bottom-width:2px}.receipt-story{padding:44px 0}.receipt-section-label{font-size:20px;gap:20px}h3{font-size:48px;margin:30px 0 36px}.receipt-summary{font-size:40px}.receipt-summary::first-letter{font-size:84px;margin:4px 12px 0 0}.receipt-index{grid-template-columns:124px minmax(0,1fr);gap:32px;padding:28px 0;border-width:2px}.receipt-index-label{font-size:22px}.receipt-index p{gap:16px 30px}.receipt-index p>span{font-size:26px}.receipt-index i{font-size:20px;margin-right:10px}.receipt-reply{padding:46px 0 40px}.receipt-reply blockquote{margin:32px 0 24px;padding-left:38px;border-width:4px}.receipt-quote-mark{font-size:86px}.receipt-reply blockquote p{font-size:52px;margin-top:-18px}.receipt-signature{font-size:24px;margin-top:28px}.receipt-footer{padding-top:38px;gap:18px;border-width:6px}.receipt-footer>em{font-size:46px}.receipt-footer>span{font-size:22px}.receipt-footer>div{font-size:20px;padding-top:24px;margin-top:16px;border-width:2px}
}
.receipt-sketch{margin:0 0 22px}.receipt-sketch img{display:block;width:100%;height:auto;aspect-ratio:4/3;object-fit:contain;mix-blend-mode:multiply}
@media screen{.journey-receipt{max-width:600px}.receipt-masthead strong{font-size:38px}}
@media screen and (orientation:portrait) and (min-width:701px){.journey-receipt{max-width:680px}}
@media screen and (orientation:portrait) and (min-width:1800px){.journey-receipt{max-width:1440px;padding:70px 85px}.receipt-masthead strong{font-size:110px}.receipt-kicker,.receipt-meta,.receipt-section-label{font-size:32px}.receipt-summary{font-size:48px;line-height:1.9}.receipt-sketch{margin:0 0 44px}.receipt-index-label{font-size:30px}.receipt-index p>span{font-size:34px}.receipt-signature{font-size:32px}.receipt-footer>div{font-size:30px}}
@media print{
  .journey-receipt{width:72mm;max-width:100%;padding:3mm 4mm;background:#fff;border:0;box-shadow:none;color:#000;break-inside:avoid}.journey-receipt::after{display:none}.receipt-masthead strong{font-size:26pt}.receipt-masthead>p{font-size:15pt;color:#000}.receipt-kicker,.receipt-meta,.receipt-section-label{font-size:7pt;color:#333}.receipt-story{padding:5mm 0}h3{font-size:15pt;margin:3mm 0}.receipt-summary{font-size:11pt;line-height:1.8}.receipt-summary::first-letter{font-size:24pt;color:#000}.receipt-index{grid-template-columns:12mm 1fr;gap:3mm;padding:3mm 0}.receipt-index-label,.receipt-index i{font-size:7pt;color:#333}.receipt-index p>span{font-size:8pt;color:#000}.receipt-reply{padding:5mm 0}.receipt-reply blockquote{margin:3mm 0;padding-left:3mm;border-color:#555}.receipt-reply blockquote p{font-size:14pt;color:#000}.receipt-quote-mark{color:#555}.receipt-signature{font-size:8pt}.receipt-footer{padding-top:4mm}.receipt-footer>em{font-size:14pt}.receipt-footer>span,.receipt-footer>div{font-size:7pt;color:#333}
}
</style>
