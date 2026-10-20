<script setup>
import JourneyIcon from './JourneyIcon.vue'
defineProps({ compact: Boolean })
</script>

<template>
  <div :class="['journey-emblem', { compact }]" aria-label="未来来电电话徽记" role="img">
    <JourneyIcon name="Phone" :size="62" />
    <JourneyIcon v-if="!compact" class="emblem-leaf" name="Sprout" :size="34" />
    <span v-if="!compact" class="emblem-signal" aria-hidden="true">✦</span>
  </div>
</template>
