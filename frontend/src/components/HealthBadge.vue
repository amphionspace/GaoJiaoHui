<script setup>
/* This check covers ASR only, never the independent TTS or text services. */
import { ref } from 'vue'
import { api } from '../core/api.js'
import { log } from '../core/store.js'

const txt = ref('网关状态未知')
const color = ref('#9aa3af')
const emit = defineEmits(['checked'])

async function checkHealth() {
  txt.value = '检查中…'; color.value = '#666'
  try {
    const h = await api('/asr/health')
    color.value = 'var(--ok)'
    txt.value = '识别服务健康检查通过'
    log('/asr/health: ' + JSON.stringify(h), 'ok')
  } catch (e) {
    if (e.status === 500) {
      color.value = 'var(--warn)'
      txt.value = '识别服务健康检查失败'
      log('识别服务健康检查返回 500，请检查后端。声音合成需单独验证。', 'err')
    } else {
      color.value = 'var(--err)'
      txt.value = '网关异常'
      log('health 失败: ' + e.message, 'err')
    }
  }
  emit('checked')
}
defineExpose({ checkHealth })
</script>

<template>
  <span class="health-dot" :style="{background: color}"></span>
  <span class="sub">{{ txt }}</span>
</template>
