<script setup>
import { ref } from 'vue'
import { api } from '../core/api.js'
import { voiceFailureMessage } from '../core/journeyAudio.js'
const props = defineProps({ apiKey: { type: String, default: '' } })
const checking = ref(false), textStatus = ref('尚未检查'), voiceStatus = ref('尚未检查')
async function check() {
  checking.value = true
  await Promise.allSettled([
    (async () => {
      try {
        const response = await fetch('/api/journey/text-status', { signal: AbortSignal.timeout(10000) })
        const body = await response.json()
        textStatus.value = response.ok ? body.configured ? `已配置 ${body.model}（待生成验证）` : '未配置文本模型，无法生成摘要与未来回信' : body.detail?.message || '文本服务配置异常'
      } catch { textStatus.value = '本地回信服务未连接' }
    })(),
    (async () => {
      if (!props.apiKey.trim()) { voiceStatus.value = '未填写语音网关密钥'; return }
      try {
        const body = await api('/tts/v1/audio/voices', { prefix: '/api/journey', headers: { 'X-API-Key': props.apiKey.trim() }, signal: AbortSignal.timeout(15000) })
        if (body instanceof Blob) throw new Error('网关返回了非接口内容，请检查路由。')
        voiceStatus.value = body.ready
          ? `${body.model} 已就绪；当前 ${body.voices?.length || 0}/${body.voice_limit} 个临时会话。音色相似度需本人录音试听。`
          : '本人声音模型正在加载，请稍后检查。'
      } catch (error) { voiceStatus.value = voiceFailureMessage(error) }
    })(),
  ])
  checking.value = false
}
</script>
<template>
  <div class="journey-service-status">
    <button type="button" class="mini" :disabled="checking" @click="check">{{ checking ? '检查中…' : '检查手记与声音服务' }}</button>
    <dl><dt>未来回信</dt><dd>{{ textStatus }}</dd><dt>本人声音</dt><dd>{{ voiceStatus }}</dd></dl>
  </div>
</template>
<style scoped>
.journey-service-status{border-top:1px solid #e3eae6;margin:16px 0;padding-top:16px;font-size:12px;line-height:1.7}dl{margin:12px 0}dt{font-weight:600}dd{margin:3px 0 12px;color:#61736b;overflow-wrap:anywhere}
</style>
