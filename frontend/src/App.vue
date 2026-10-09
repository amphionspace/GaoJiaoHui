<script setup>
/* 应用壳：头部（健康徽章 / API Key / 演示模式）+ Tab 导航 + 模块组件 + 日志
   Tab1 = 「未来手记」电话亭旅程（三问连讲，设计稿 01–08 的逻辑实现）
   Tab2 = 多人对话工作台（完整复刻 portal playground/target-dialogue：注册声纹、声纹管理、
         目标选择、边聊边采集、锁定目标、热词、实时对话 turn 流；接口仅用声纹注册 HTTP +
         流式转写 WS /asr/v1/target-dialogue；原调试·流式转写 / 多人分离 / 声纹克隆页暂下线，组件文件保留） */
import { ref, onMounted } from 'vue'
import { store, setApiKey } from './core/store.js'
import HealthBadge from './components/HealthBadge.vue'
import LogPanel from './components/LogPanel.vue'
import BoothJourney from './components/BoothJourney.vue'
import ModuleWorkbench from './components/ModuleWorkbench.vue'
import ModuleVoiceClone from './components/ModuleVoiceClone.vue'

const TABS = ['未来手记旅程', '多人对话工作台', '声音克隆对话']
const tab = ref(0)
const keyInput = ref(store.apiKey)
const health = ref(null)

onMounted(() => { health.value && health.value.checkHealth() })
</script>

<template>
  <header>
    <h1>Amphion 语音接口 Demo</h1>
    <div class="keybox">
      <HealthBadge ref="health" />
      <input class="apikey" type="text" v-model="keyInput" placeholder="API Key（sk-...）"
        spellcheck="false" @change="setApiKey(keyInput)">
      <label class="sub" style="display:inline-flex;gap:5px;align-items:center;cursor:pointer">
        <input type="checkbox" v-model="store.demoMode">演示模式</label>
      <button class="mini" @click="health.checkHealth()">检查</button>
    </div>
  </header>
  <nav>
    <button v-for="(t, i) in TABS" :key="i" :class="{active: tab === i}" @click="tab = i">{{ t }}</button>
  </nav>
  <main :class="{ wide: tab >= 1 }">
    <BoothJourney v-show="tab === 0" />
    <ModuleWorkbench v-show="tab === 1" />
    <ModuleVoiceClone v-show="tab === 2" />
    <LogPanel />
  </main>
</template>
