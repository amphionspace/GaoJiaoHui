<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { ArrowLeft, Copy, Check, Maximize2 } from '@lucide/vue'
import { store } from '../core/store.js'

const viewport = ref(null), shell = ref(null), scale = ref(.15), copied = ref(false)
const source = computed(() => {
  const url = new URL(window.location.href)
  url.searchParams.delete('view')
  url.searchParams.set('display', 'kiosk')
  url.searchParams.set('lang', store.locale)
  return url.href
})
const frameStyle = computed(() => ({ width: `${2160 * scale.value}px`, height: `${3840 * scale.value}px` }))
let observer, copyTimer
async function copyLink() {
  try {
    await navigator.clipboard.writeText(source.value)
    copied.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copied.value = false }, 2500)
  } catch { copied.value = false }
}
function fullscreen() { shell.value?.requestFullscreen?.().catch(() => {}) }
onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    scale.value = Math.max(.01, Math.min(entry.contentRect.width / 2160, entry.contentRect.height / 3840))
  })
  observer.observe(viewport.value)
})
onBeforeUnmount(() => { observer?.disconnect(); clearTimeout(copyTimer) })
</script>

<template>
  <div ref="shell" class="portrait-experience">
    <div class="portrait-toolbar">
      <a href="/" aria-label="返回普通页面" title="返回普通页面"><ArrowLeft :size="20" /></a>
      <span>和 2036 对话 <small>竖屏体验</small></span>
      <button :title="copied ? '链接已复制' : '复制体验链接'" :aria-label="copied ? '链接已复制' : '复制体验链接'" @click="copyLink"><Check v-if="copied" :size="20" /><Copy v-else :size="20" /></button>
      <button title="全屏体验" aria-label="全屏体验" @click="fullscreen"><Maximize2 :size="20" /></button>
      <span class="portrait-copy-status" role="status">{{ copied ? '链接已复制' : '' }}</span>
    </div>
    <div ref="viewport" class="portrait-viewport">
      <div class="portrait-screen" :style="frameStyle">
        <iframe title="和 2036 对话竖屏体验" :src="source" allow="microphone; autoplay; fullscreen" :style="{ transform: `scale(${scale})` }" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.portrait-experience{height:100dvh;display:flex;flex-direction:column;background:#d9ded8;color:#37443b;overflow:hidden}
.portrait-toolbar{min-height:54px;display:flex;gap:12px;align-items:center;flex:none;padding:8px 20px;position:relative}
.portrait-toolbar>span:first-of-type{flex:1;font-size:13px;font-weight:600}.portrait-toolbar small{font-size:11px;font-weight:400;color:#69756a;margin-left:10px}
.portrait-toolbar :is(button,a){display:grid;place-items:center;min-width:38px;height:38px;padding:0;border:1px solid #b8c0b5;background:#edf0e9;color:inherit;border-radius:50%;cursor:pointer;text-decoration:none;transition:background .2s,transform .2s}.portrait-toolbar :is(button,a):hover{background:#fff;transform:translateY(-1px)}.portrait-toolbar :is(button,a):focus-visible{outline:2px solid #506a56;outline-offset:3px}
.portrait-copy-status{position:absolute;right:70px;top:52px;font-size:11px;z-index:2;background:#edf0e9;border-radius:4px}.portrait-copy-status:not(:empty){padding:6px 10px}
.portrait-viewport{flex:1;min-height:0;margin:0 18px 18px;display:flex;justify-content:center;align-items:center}
.portrait-screen{flex:none;position:relative;overflow:hidden;box-shadow:0 0 0 1px #adb7a8,0 12px 50px #35432e26;background:#f3f3ef;border-radius:8px}
.portrait-screen iframe{display:block;position:absolute;left:0;top:0;width:2160px;height:3840px;max-width:none;border:0;transform-origin:0 0;color-scheme:light}
@media(max-width:600px){.portrait-toolbar{padding:6px 12px}.portrait-viewport{margin:0 6px 10px}}
@media(prefers-reduced-motion:reduce){.portrait-toolbar :is(button,a){transition:none}}
</style>
