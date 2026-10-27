<script setup>
/* 应用壳：头部（健康徽章 / API Key / 演示模式）+ Tab 导航 + 模块组件 + 日志
   Tab1 = 「未来手记」电话亭旅程（三问连讲，设计稿 01–08 的逻辑实现）
   Tab2 = 多人对话工作台（完整复刻 portal playground/target-dialogue：注册声纹、声纹管理、
         目标选择、边聊边采集、锁定目标、热词、实时对话 turn 流；接口仅用声纹注册 HTTP +
         流式转写 WS /asr/v1/target-dialogue；原调试·流式转写 / 多人分离 / 声纹克隆页暂下线，组件文件保留） */
import { ref, onMounted, watch } from 'vue'
import { store, setApiKey } from './core/store.js'
import { toggleLocale, tr } from './core/i18n.js'
import HealthBadge from './components/HealthBadge.vue'
import LogPanel from './components/LogPanel.vue'
import BoothJourney from './components/BoothJourney.vue'
import ModuleWorkbench from './components/ModuleWorkbench.vue'
import ModuleVoiceClone from './components/ModuleVoiceClone.vue'
import JourneyIcon from './components/JourneyIcon.vue'
import JourneyServiceStatus from './components/JourneyServiceStatus.vue'
import JourneyPortrait from './components/JourneyPortrait.vue'
import { Smartphone } from '@lucide/vue'

const portraitPreview = new URLSearchParams(window.location.search).get('view') === 'portrait'
const kiosk = new URLSearchParams(window.location.search).get('display') === 'kiosk'

const TABS = ['未来手记旅程', '多人对话工作台', '声音克隆对话']
const tab = ref(0)
const keyInput = ref(store.apiKey)
watch(() => store.apiKey, key => { keyInput.value = key })
const health = ref(null)
const settings = ref(null)
function openSettings() { settings.value?.showModal() }
function saveSettings() { setApiKey(keyInput.value); settings.value?.close() }
function changeLanguage() { toggleLocale() }

onMounted(() => { health.value && health.value.checkHealth() })
</script>

<template>
  <JourneyPortrait v-if="portraitPreview" />
  <template v-else>
  <header v-if="tab !== 0">
    <h1>Amphion 语音工作台</h1>
    <div class="keybox">
      <HealthBadge ref="health" />
      <input class="apikey" type="password" v-model="keyInput" placeholder="API Key（sk-...）"
        spellcheck="false" @change="setApiKey(keyInput)">
      <label class="sub" style="display:inline-flex;gap:5px;align-items:center;cursor:pointer">
        <input type="checkbox" v-model="store.demoMode">简洁日志</label>
      <button class="mini" @click="health.checkHealth()">检查</button>
      <button class="mini language-switch" type="button" @click="changeLanguage">{{ store.locale === 'en' ? '中' : 'EN' }}</button>
    </div>
  </header>
  <div v-else class="journey-appbar"><span><JourneyIcon name="Phone" :size="18" />和 2036 对话 <small>demo1</small></span><div class="journey-appbar-actions"><button class="language-switch" type="button" @click="changeLanguage">{{ store.locale === 'en' ? '中' : 'EN' }}</button><a v-if="!kiosk" :href="`?view=portrait&lang=${store.locale}`" title="竖屏体验" aria-label="竖屏体验"><Smartphone :size="19" /></a><button title="连接设置" aria-label="连接设置" @click="openSettings"><JourneyIcon name="Settings2" :size="19" /></button></div></div>
  <nav v-if="tab !== 0">
    <button v-for="(t, i) in TABS" :key="i" :class="{active: tab === i}" @click="tab = i">{{ t }}</button>
  </nav>
  <main :class="{ wide: tab >= 1, 'journey-main': tab === 0 }">
    <BoothJourney v-show="tab === 0" :active="tab === 0" @settings="openSettings" />
    <ModuleWorkbench v-show="tab === 1" :active="tab === 1" />
    <ModuleVoiceClone v-show="tab === 2" :active="tab === 2" />
    <LogPanel v-if="tab !== 0" />
  </main>
  <dialog ref="settings" class="journey-settings">
    <form @submit.prevent="saveSettings"><div class="settings-heading"><h2>连接设置</h2><button type="button" aria-label="关闭设置" title="关闭设置" @click="settings.close()"><JourneyIcon name="X" /></button></div>
      <label for="journey-api-key">语音网关密钥</label><input id="journey-api-key" type="password" v-model="keyInput" placeholder="sk-..." autocomplete="off" spellcheck="false" />
      <JourneyServiceStatus :api-key="keyInput" />
      <button type="submit" class="act">保存设置</button>
    </form><details><summary>其他工作台</summary><div class="settings-modules"><button v-for="(t, i) in TABS.slice(1)" :key="t" @click="tab = i + 1; settings.close()">{{ t }}</button></div></details><details><summary>运行记录</summary><LogPanel /></details>
  </dialog>
  </template>
</template>

<style>
.journey-appbar-actions{display:flex;align-items:center;gap:16px}.journey-appbar-actions a{display:flex;color:#526a5c;padding:4px}
@media(orientation:portrait) and (min-width:1800px){dialog.journey-settings{width:1200px;padding:60px;font-size:32px}dialog.journey-settings .settings-heading h2{font-size:42px}dialog.journey-settings .settings-heading{margin-bottom:50px}dialog.journey-settings form>label,dialog.journey-settings summary{font-size:30px}dialog.journey-settings input{font-size:34px;padding:28px}dialog.journey-settings :is(button,.journey-service-status){font-size:30px}dialog.journey-settings button{min-height:80px;padding:16px 24px}dialog.journey-settings svg{width:40px;height:40px}}
main.journey-main{max-width:1440px;padding:0;margin:0 auto}.journey-appbar{display:flex;align-items:center;justify-content:space-between;padding:14px 28px 10px;background:#fff;border-bottom:1px solid #eef1f0}.journey-appbar>span{display:flex;align-items:center;gap:9px;font-size:12px;font-weight:650;color:#3c5b52}.journey-appbar small{font-size:11px;font-weight:400;color:#81928b;margin-left:7px}.journey-appbar button{border:0;background:transparent;color:#71877d;cursor:pointer;padding:4px;display:flex}.journey-tabs{padding:0 24px;background:#fff;gap:20px}.journey-tabs button{padding:11px 2px;font-size:11px;border-radius:0;border:0;color:#83918d}.journey-tabs button.active{background:transparent;color:#305b4b;border:0;border-bottom:2px solid #507c67}.journey-settings{border:1px solid #d2ded8;border-radius:8px;width:480px;max-width:calc(100% - 32px);padding:25px;color:#2a3e35}.journey-settings::backdrop{background:#152a394d}.settings-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:23px}.settings-heading h2{font-size:18px;margin:0}.settings-heading button{display:flex;background:none;border:0;cursor:pointer;color:inherit}.journey-settings form>label{display:block;font-size:12px;margin:12px 0 8px}.journey-settings input{width:100%;border:1px solid #cbdad1;border-radius:6px;padding:12px}.settings-health{display:flex;gap:14px;align-items:center;margin:18px 0}.journey-settings details{border-top:1px solid #e3eae6;margin-top:25px;padding-top:15px}.journey-settings summary{font-size:12px;cursor:pointer;margin-bottom:15px}@media(max-width:420px){.journey-appbar{padding:12px 17px 8px}.journey-tabs{gap:20px;padding:0 17px}.journey-tabs button{font-size:10px}}
</style>
