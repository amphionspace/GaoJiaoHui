<script setup>
import { computed } from 'vue'
import { store } from '../core/store.js'
import layout from '../core/guideLayout.json'

defineProps({ revealAll: { type: Boolean, default: false } })
defineEmits(['start', 'text', 'replay', 'skip'])
const english = computed(() => store.locale === 'en')
const translations = {
  intro_line_1: 'From 2016 to 2026,', intro_line_2: 'ten years have changed everyday life.',
  caption_toy_robot: 'Remote-controlled toy robot', caption_boxing_robots: 'Robots in the boxing ring',
  caption_search: 'Searching for information', caption_ai: 'AI answers and creation',
  caption_driving: 'Everyday driving', caption_flying_car: 'Flying car demonstration',
  caption_flying_note: 'Off public roads', question_line_1: 'What do you hope the world',
  question_line_2: 'will be like in ten years?',
}
const layers = layout.assets.filter(a => !['button', 'button_part'].includes(a.type))
const button = layout.assets.find(a => a.id === 'button_background')
// Pair each illustration with its caption; crop coordinates do not define timing.
const revealGroups = [
  ['01_toy_robot', 'caption_toy_robot'],
  ['02_boxing_robots', 'caption_boxing_robots', 'arrow_robot'],
  ['03_search_laptop', 'caption_search'],
  ['04_ai_creative', 'caption_ai', 'arrow_search'],
  ['05_driving_car', 'caption_driving'],
  ['06_flying_car', 'caption_flying_car', 'caption_flying_note', 'arrow_car'],
]
const revealDelays = new Map(revealGroups.flatMap((ids, index) =>
  ids.map(id => [id, 1.8 + index * 1.2])))
function delay(a) {
  if (revealDelays.has(a.id)) return revealDelays.get(a.id)
  if (['background', 'scenery'].includes(a.type)) return 0
  if (a.y < 250) return .6
  return 9.2
}
function position(a) {
  return { left: `${a.x_percent}%`, top: `${a.y_percent}%`, width: `${a.width_percent}%`, height: `${a.height_percent}%`, zIndex: a.z, '--delay': `${delay(a)}s` }
}
</script>

<template>
  <div class="guide-wrapper">
    <section class="guide-poster" :class="{ 'guide-revealed': revealAll }" :aria-label="english ? '2016 to 2026, looking ahead to 2036' : '2016 到 2026，展望 2036'">
      <template v-for="layer in layers" :key="layer.id">
        <span v-if="english && translations[layer.id]" class="guide-layer guide-translation" :style="position(layer)">{{ translations[layer.id] }}</span>
        <img v-else class="guide-layer" :class="{ 'guide-background': ['background', 'scenery'].includes(layer.type) }" :style="position(layer)" :src="`/journey/guide/${layer.file}`" :alt="layer.text || (layer.type === 'illustration' ? layer.name : '')" draggable="false" />
      </template>
      <button class="guide-start" :style="position(button)" :aria-label="english ? 'Start speaking' : '开始说话'" @click="$emit('start')">
        <img v-if="!english" src="/journey/guide/05_button/button_label.png" alt="开始说话" />
        <span v-else>Start speaking</span>
        <img class="guide-mic" src="/journey/guide/05_button/microphone.png" alt="" />
      </button>
    </section>
    <div class="guide-tools">
      <button class="guide-continue" @click="$emit('start')">{{ english ? 'Start speaking' : '说说我的期待' }}</button>
      <button v-if="!revealAll" @click="$emit('skip')">{{ english ? 'Skip animation' : '跳过动画' }}</button>
      <button @click="$emit('replay')">{{ english ? 'Replay' : '重新观看' }}</button>
      <button @click="$emit('text')">{{ english ? 'Use text instead' : '改用文字' }}</button>
    </div>
  </div>
</template>

<style scoped>
.guide-wrapper{width:100%;margin:auto}
.guide-poster{position:relative;width:100%;aspect-ratio:941/1672;isolation:isolate;container-type:inline-size;background:#f4ebdf;overflow:hidden}
.guide-layer{position:absolute;display:block;max-width:none;object-fit:fill;animation:guide-reveal 1.1s var(--delay) both;pointer-events:none}
.guide-layer.guide-background{animation:none}
.guide-revealed .guide-layer,.guide-revealed .guide-start{animation:none;visibility:visible;opacity:1;transform:none}
.guide-translation{display:flex;align-items:center;justify-content:center;text-align:center;color:#263c32;font:2.5cqw/1.1 Georgia,serif}
.guide-start{position:absolute;z-index:40!important;border:0;padding:0;border-radius:999px;background:#354d39 url('/journey/guide/05_button/button_background.png') center/100% 100%;color:white;display:flex;align-items:center;justify-content:center;gap:4%;animation:guide-reveal 1.1s 9.5s both;cursor:pointer}
.guide-start>img:not(.guide-mic){width:40%;height:auto;margin-left:12%}.guide-start .guide-mic{position:absolute;left:18%;width:9%;height:auto}.guide-start span{font:3.3cqw/1.2 sans-serif;margin-left:12%}
.guide-start:focus-visible{outline:3px solid #ac573e;outline-offset:5px}.guide-start:hover{filter:brightness(1.08)}
.guide-tools{display:flex;justify-content:center;gap:24px;padding:8px;background:#f4ebdf}.guide-tools button{border:0;background:none;color:#5e6659;font-size:13px;cursor:pointer;text-decoration:underline;text-underline-offset:4px}
@keyframes guide-reveal{from{opacity:0;transform:translateY(8px);visibility:hidden}to{opacity:1;transform:none;visibility:visible}}
@media(orientation:portrait) and (min-width:1800px){.guide-tools{padding:12px;gap:48px}.guide-tools button{font-size:28px}}
@media(prefers-reduced-motion:reduce){.guide-layer,.guide-start{animation:none}}
</style>
