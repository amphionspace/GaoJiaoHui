<template>
  <div class="wind-letters" aria-hidden="true">
    <span v-for="i in 3" :key="i" class="wind-letter" :style="{ '--sheet': i }"><i /><i /><i /><b /></span>
  </div>
</template>

<style scoped>
.wind-letters{position:relative;width:270px;height:170px;flex:none;perspective:650px}
.wind-letter{position:absolute;left:94px;top:50px;width:61px;height:83px;padding:21px 10px 10px;background:#fafaf5;border:1px solid #bfc4b7;box-shadow:3px 7px 13px #3a493019;transform-origin:50% 70%;animation:letter-in-wind 5.4s calc(var(--sheet) * -1.8s) ease-in-out infinite}
.wind-letter:nth-child(2){background:#e5ebe3}.wind-letter:nth-child(3){background:#f0e5df}
.wind-letter i{display:block;height:1px;background:#aab2a2;margin-bottom:7px}.wind-letter i:nth-child(2){width:78%}.wind-letter i:nth-child(3){width:58%}.wind-letter b{position:absolute;right:8px;top:8px;width:9px;height:10px;border:1px solid #b47b6e}
@keyframes letter-in-wind{0%{opacity:0;transform:translate(-105px,28px) rotate(-26deg) rotateY(35deg) scale(.55)}18%{opacity:.8}45%{opacity:1;transform:translate(-12px,-19px) rotate(8deg) rotateY(-15deg) scale(1)}72%{opacity:.85;transform:translate(59px,-2px) rotate(-8deg) rotateY(20deg) scale(.87)}100%{opacity:0;transform:translate(115px,-60px) rotate(28deg) rotateY(-30deg) scale(.55)}}
@media(orientation:portrait) and (min-width:1800px){.wind-letters{zoom:2}}
@media(prefers-reduced-motion:reduce){.wind-letter{animation:none;opacity:1;transform:translate(calc((var(--sheet) - 2) * 60px),calc((var(--sheet) - 2) * -12px)) rotate(calc((var(--sheet) - 2) * 12deg))}}
</style>
