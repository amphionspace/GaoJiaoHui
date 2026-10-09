<script setup>
/* 波形绘制：Int16Array[] -> canvas 峰值图（接口三参考音频） */
import { ref, watch, onMounted } from 'vue'

const props = defineProps({ chunks: { type: Array, default: () => [] } })
const cv = ref(null)

function draw() {
  const el = cv.value; if (!el) return
  const ctx = el.getContext('2d')
  el.width = el.offsetWidth || 600; el.height = 46
  ctx.clearRect(0, 0, el.width, el.height); ctx.fillStyle = '#4f8cff'
  const all = props.chunks.flat(), step = Math.max(1, Math.floor(all.length / el.width))
  for (let x = 0; x < el.width; x++) {
    let m = 0
    for (let i = x * step; i < (x + 1) * step && i < all.length; i++)
      m = Math.max(m, Math.abs(all[i]) / 32768)
    const h = Math.max(1, m * el.height)
    ctx.fillRect(x, (el.height - h) / 2, 1, h)
  }
}
watch(() => props.chunks, draw, { deep: false })
onMounted(draw)
defineExpose({ draw })
</script>

<template>
  <canvas ref="cv" style="width:100%;height:46px;background:var(--panel2);border-radius:8px;margin-top:8px"></canvas>
</template>
