<script setup>
import { Mail } from '@lucide/vue'
</script>

<template>
  <div class="meteor-space" aria-hidden="true">
    <i v-for="n in 28" :key="n" class="meteor-star" :style="{ left: `${(n * 37) % 100}%`, top: `${(n * 23) % 92}%`, animationDelay: `${n * -.3}s` }" />
    <div class="meteor-orbit" />
    <div class="meteor-letter"><span class="meteor-trail" /><Mail :stroke-width="1" /></div>
    <span class="meteor-year">2036</span>
  </div>
</template>

<style scoped>
.meteor-space{position:relative;width:min(720px,100%);aspect-ratio:4/3;overflow:hidden;color:#f9faf4;isolation:isolate;background:#202c2b;mask-image:radial-gradient(ellipse at center,#000 35%,transparent 70%)}
.meteor-star{position:absolute;width:2px;height:2px;background:#d9e9dc;border-radius:50%;animation:meteor-twinkle 3.2s ease-in-out infinite}.meteor-star:nth-child(4n){width:4px;height:4px;background:#e8b098}
.meteor-orbit{position:absolute;width:150%;height:90%;border:1px solid #98b8a044;border-radius:50%;left:-28%;top:58%;transform:rotate(-20deg)}
.meteor-letter{position:absolute;left:23%;top:64%;width:52px;height:40px;animation:meteor-launch 4.8s cubic-bezier(.35,.05,.35,1) infinite;transform:rotate(-25deg)}.meteor-letter svg{width:100%;height:100%;fill:#eef2e7;stroke:#567363;position:relative;filter:drop-shadow(0 0 8px #e2eddc70)}
.meteor-trail{position:absolute;right:40%;top:60%;width:180px;height:3px;background:linear-gradient(90deg,transparent,#d2e6ce);transform:rotate(-18deg);transform-origin:100% 50%;box-shadow:0 3px 12px #d2e6ce55}
.meteor-year{position:absolute;right:21%;top:23%;font:italic 22px Georgia,serif;color:#cbd6c5}
@keyframes meteor-launch{0%{opacity:0;transform:translate(-30px,40px) rotate(-25deg) scale(.9)}18%{opacity:1}72%{opacity:1}100%{opacity:0;transform:translate(300px,-230px) rotate(-35deg) scale(.15)}}
@keyframes meteor-twinkle{50%{opacity:.2;transform:scale(.6)}}
@media(orientation:portrait) and (min-width:1800px){.meteor-space{width:1500px}.meteor-letter{width:110px;height:85px}.meteor-trail{width:380px;height:5px}.meteor-star{width:5px;height:5px}.meteor-star:nth-child(4n){width:8px;height:8px}.meteor-year{font-size:54px}@keyframes meteor-launch{0%{opacity:0;transform:translate(-70px,80px) rotate(-25deg) scale(.9)}18%{opacity:1}72%{opacity:1}100%{opacity:0;transform:translate(650px,-480px) rotate(-35deg) scale(.15)}}}
@media(max-width:500px){.meteor-letter{width:36px;height:28px}.meteor-trail{width:100px}.meteor-year{font-size:16px}@keyframes meteor-launch{0%{opacity:0;transform:translate(-10px,20px) rotate(-25deg)}18%{opacity:1}72%{opacity:1}100%{opacity:0;transform:translate(150px,-120px) rotate(-35deg) scale(.15)}}}
@media(prefers-reduced-motion:reduce){.meteor-letter{left:50%;top:45%;animation:none}.meteor-star{animation:none}}
</style>
