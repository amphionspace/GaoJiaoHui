<script setup>
import icons from '../core/journeyIcons.js'
import { Phone } from '@lucide/vue'
defineProps({ name: { type: String, required: true }, size: { type: [Number, String], default: 20 } })
</script>
<template>
  <Phone v-if="name === 'Phone'" :size="size" :stroke-width="1.7" aria-hidden="true" class="journey-icon" />
  <svg v-else :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="journey-icon">
    <component :is="node[0]" v-for="(node, i) in icons[name] || icons.Sparkles" :key="i" v-bind="node[1]" />
  </svg>
</template>
<style scoped>.journey-icon { flex-shrink: 0; vertical-align: middle; }</style>
