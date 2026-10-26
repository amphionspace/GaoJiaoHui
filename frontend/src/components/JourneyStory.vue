<script setup>
defineProps({ chapter: { type: Number, default: 0 } })
const scenes = ['蓝牙耳机与第一代无线耳机', '围棋棋盘与落子', '城市中的无人驾驶汽车', '驶向太空的红色跑车']
</script>

<template>
  <div class="story-scenes" role="img" :aria-label="scenes[chapter]">
    <Transition name="story-scene">
      <div :key="chapter" class="story-scene" :class="`story-scene-${chapter}`" aria-hidden="true" />
    </Transition>
    <div class="story-progress" aria-hidden="true"><i v-for="i in 4" :key="i" :class="{ active: i - 1 === chapter }" /></div>
  </div>
</template>

<style scoped>
.story-scenes{width:100%;aspect-ratio:3/2;position:relative;isolation:isolate}
.story-scene{position:absolute;inset:0;background-image:url('/journey/story-2036.png');background-size:200% 200%;background-repeat:no-repeat;mix-blend-mode:multiply;animation:story-drift 25s ease-in-out both;mask-image:linear-gradient(transparent,#000 7%,#000 93%,transparent)}
.story-scene-0{background-position:0 0}.story-scene-1{background-position:100% 0}.story-scene-2{background-position:0 100%}.story-scene-3{background-position:100% 100%}
.story-scene-enter-active,.story-scene-leave-active{transition:opacity 1.8s ease,filter 1.8s ease}.story-scene-enter-from,.story-scene-leave-to{opacity:0;filter:blur(8px)}
.story-progress{position:absolute;bottom:-22px;left:0;right:0;display:flex;justify-content:center;gap:10px}.story-progress i{width:24px;height:2px;background:#c6cec3;transition:background 1s,width 1s}.story-progress .active{background:#738370;width:44px}
@keyframes story-drift{from{transform:translateY(12px) scale(.96)}to{transform:translateY(-6px) scale(1.02)}}
@media(orientation:portrait) and (min-width:1800px){.story-progress{bottom:-60px;gap:24px}.story-progress i{width:60px;height:5px}.story-progress .active{width:110px}}
@media(prefers-reduced-motion:reduce){.story-scene{animation:none}.story-scene-enter-active,.story-scene-leave-active,.story-progress i{transition:none}}
</style>
