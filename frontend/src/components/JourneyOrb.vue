<script setup>
import { computed } from 'vue'
const props = defineProps({ state: { type: String, default: 'idle' }, level: { type: Number, default: 0 } })
const energy = computed(() => props.state === 'listening' ? Math.max(0, Math.min(1, props.level)) : 0)
</script>
<template>
  <div class="voice-orb" :data-state="state" :style="{ '--energy': energy }" aria-hidden="true">
    <div class="orb-halo" /><div class="orb-ring" /><div class="orb-body"><span /><i /></div>
    <div class="orb-shadow" />
  </div>
</template>
<style scoped>
.voice-orb{position:relative;width:clamp(180px,32vw,290px);aspect-ratio:1;flex:none;margin:12px auto;isolation:isolate}
.orb-halo{position:absolute;inset:0;border-radius:50%;background:radial-gradient(circle,#dcecf4a0,transparent 69%);transform:scale(calc(1.12 + var(--energy)*.3));transition:transform .13s}
.orb-ring{position:absolute;inset:9%;border:1px solid #c6dce6aa;border-radius:50%;transform:scale(calc(1 + var(--energy)*.16));transition:transform .13s}
.orb-body{position:absolute;inset:19%;border-radius:46% 54% 52% 48%;background:radial-gradient(ellipse at 30% 22%,#fffef9 0%,#e3f0f4 25%,#aacddd 58%,#749bae 87%);box-shadow:inset -9px -10px 24px #648da54a,inset 8px 6px 17px #ffffffd0,0 16px 38px #81a7bb30;transform:scale(calc(1 + var(--energy)*.13));transition:transform .12s,border-radius .4s;overflow:hidden}
.orb-body span{position:absolute;inset:45% -10% -20% 20%;border-radius:50%;background:#f2c9ad8a;filter:blur(15px)}
.orb-body i{position:absolute;inset:12% 30% 48% 13%;background:#ffffffa0;filter:blur(12px);border-radius:50%}
.orb-shadow{position:absolute;bottom:3%;left:32%;right:32%;height:7%;border-radius:50%;background:#7d9ca424;filter:blur(10px)}
[data-state=connecting] .orb-ring,[data-state=processing] .orb-ring{border-top:2px solid #789eaf;animation:orb-turn 2.8s linear infinite}
[data-state=processing] .orb-body{animation:orb-think 3s ease-in-out infinite}
[data-state=speaking] .orb-body{animation:orb-think 1.5s ease-in-out infinite}
[data-state=error] .orb-body{background:radial-gradient(ellipse at 30% 22%,#fff7ef,#eed5c1 50%,#c99e86)}
[data-state=paused] .orb-body,[data-state=typing] .orb-body{filter:saturate(.45)}
@keyframes orb-turn{to{transform:rotate(360deg)}}@keyframes orb-think{50%{transform:scale(1.04);border-radius:54% 46% 47% 53%}}
@media(prefers-reduced-motion:reduce){.voice-orb *{animation:none!important;transition:none!important}.orb-body,.orb-ring,.orb-halo{transform:none!important}}
</style>
