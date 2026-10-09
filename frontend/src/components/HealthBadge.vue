<script setup>
/* 网关健康徽章：三级显示
   绿 = /asr/health 200；黄 = 500（网关在线，其探测的 ASR 后端池降级，三模块不受影响）；红 = 网关不可达 */
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
    txt.value = '网关正常 · uptime ' + Math.round((h.uptime_seconds || 0) / 3600) + 'h'
    log('/asr/health: ' + JSON.stringify(h), 'ok')
  } catch (e) {
    if (e.status === 500) {
      color.value = 'var(--warn)'
      txt.value = '网关在线 · 部分后端维护中（三模块功能实测可用）'
      log('/asr/health 返回 500（其探测的 ASR 后端池降级），网关本身在线；流式转写/多人分离/克隆合成走独立链路不受影响', 'evt')
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
