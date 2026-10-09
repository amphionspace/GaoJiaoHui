<script setup>
/* 事件日志面板：着色 + 自动滚底 + 清空 */
import { ref, watch, nextTick } from 'vue'
import { store } from '../core/store.js'

const box = ref(null)
watch(() => store.logs.length, async () => {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
})
function clear() { store.logs.length = 0 }
</script>

<template>
  <div class="card">
    <h2>事件日志 <button class="mini" @click="clear">清空</button></h2>
    <div class="logbox" ref="box">
      <div v-for="(l, i) in store.logs" :key="i" :class="l.cls ? 'l-' + l.cls : ''">[{{ l.time }}] {{ l.msg }}</div>
      <div v-if="!store.logs.length">（暂无日志）</div>
    </div>
  </div>
</template>
