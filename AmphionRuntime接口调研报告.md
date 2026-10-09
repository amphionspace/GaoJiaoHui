# AmphionRuntime 语音接口调研报告

> 仓库：https://github.com/amphionspace/AmphionRuntime（main 分支）
> 调研方式：未克隆/未拉取整个仓库。基于本地已有 git 对象执行 `git ls-tree --name-only HEAD` / `git ls-tree -r origin/main` 浏览文件树 + GitHub raw API 按需读取单个文件。
> 调研日期：2026-09-29（远端最新提交 `acf477c` "fix/diarization-unknown-fallback"，2026-09-29）

仓库一级结构：`asr/`（语音识别）、`tts/`（语音合成）、`docs/`、`delivery/`（鼎桥等客户交付）、`shared/`、`tools/`、`third_party/`（内嵌 sherpa-onnx）。
核心接口文档：
- `asr/server/API.md`（gRPC 服务接口）
- `asr/ws-server/README.md`（WebSocket 服务接口）
- `asr/android/docs/customer/语音识别SDK接口.md`（端侧 SDK 接口，Android/HarmonyOS 通用契约）
- `delivery/harmony-dingqiao/docs/customer/DINGQIAO_ASR_INTEGRATION.md`（鸿蒙集成指南）
- `asr/android/docs/Target_speaker.md`、`docs/speaker/PIPELINE.md`（目标说话人/多人场景方案）

---

## 一、可用的语音转文字接口（单说话人 ASR）

### 1. 服务端 gRPC 接口（`asr/server/`，proto 定义 `asr/server/proto/asr.proto`）

服务 `asr.v1.AsrService`，gRPC over HTTP/2，明文 h2c，单消息上限 8 MB：

| 方法 | 类型 | 说明 |
|---|---|---|
| `Recognize(stream PcmRequest) returns (stream AsrEvent)` | 双向流 | **流式语音转文字主接口** |
| `Healthz` | 一元 | 健康检查（status / active_sessions / recent_rtf） |
| `ServerInfo` | 一元 | 服务端版本与模型信息（含采样率，可查询） |

调用流程：首帧 `SessionConfig`（audio_format、hotwords 热词、include_token_timestamps）→ 持续发送 `AudioChunk`（建议 100ms/帧，16k 单声道 PCM_S16LE 为 3200 字节）→ 服务端返回 `session_started / partial(中间结果) / endpoint(断句) / final(最终结果) / error / session_ended` 事件；期间可发 `UpdateHotwordsRequest` 动态更新热词；结束发 `EndOfStream`。
final 结果含 `text、confidence、tokens、timestamps、token_confidences`。

### 2. 服务端 WebSocket 接口（`asr/ws-server/`，Python，Linux/Mac CPU → H20 CUDA）

- 启动：`python -m amphion_asr_ws --listen=127.0.0.1:8010 --manifest=deploy/manifest.local.cpu.json ...`
- 协议：JSON `start` 帧（trace_id、audio_format{16000/pcm_s16le/1ch}、hotwords、include_token_timestamps）→ 二进制 PCM 帧（建议 100ms）→ JSON `stop` 帧
- 返回事件：`session_started / partial / endpoint / final / error / session_ended`
- 示例客户端：`asr/ws-server/examples/ws_client.py`；批量压测 `bench_concurrent.py`
- **注意**：文档明确"当前服务是单流 ASR，不做说话人分离、声纹跟踪或多人重叠分离"

### 3. 端侧离线 SDK（三端）

| 平台 | 入口 | 位置 |
|---|---|---|
| Android | `SpeechRecognizeSdk`（包名 `com.amphion.dingqiao`）/ 通用层 `AsrEngine.newSession()` | `asr/android/sdk-dingqiao/.../SpeechRecognizeSdk.kt`、`asr/android/sdk/src/main/java/com/amphion/asr/AsrEngine.kt` |
| HarmonyOS | `SpeechRecognizeSdk`（模块 `amphion_dingqiao`，HAR） | `asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets` |
| iOS | `SpeechRecognizeSdk` / `AsrEngine` | `asr/ios/Sources/AmphionRuntime/` |

核心调用链（三端一致）：
```
init(context) → setWorkPath → setLicense → prepareRuntime → createEngine(Async)
→ engine.setListener(...) → startListening(StartParams) → writeAudio(sessionId, 640字节PCM帧/20ms)
→ finish(sessionId) → onComplete → shutdown()
```
- 音频格式固定：16 kHz、16 bit、单声道 PCM（`AudioInfo`，仅支持 pcm/16000/16/1）
- 语言：`zh-CN`、`zh-en`（中英）；`recognizerMode=short|long`（long = 会议/持续转写）
- 结果回调 `SpeechRecognitionResult`：`isFinal / isLast / result(文本) / beginTime / endTime / speakerSimilarity / utteranceId / speakerIndex ...`
- 支持热词（`sysGeneralLexicon`）、警务术语增强、VAD 参数（vadBegin/vadEnd）、`maxAudioDuration`


---

## 二、多人场景下语音转文字接口

### 1. 说话人分离（Speaker Diarization，完全离线，Android/HarmonyOS 双端）

**启用方式**（会话级参数，`StartParams.speakerDiarization`）：
```kotlin
startListening(StartParams(
    sessionId, AudioInfo(),
    speakerDiarization = SpeakerDiarizationConfig(maxSpeakers = 4)  // 1~4
))
```
**回调接口**（`RecognitionListener`）：
- `onSpeakerDiarizationUpdate(sessionId, update)` — 说话人归属修订（utteranceId + revision 覆盖旧显示）
- `onSpeakerDiarizationResult(sessionId, result)` — 分窗定稿结果（约 120 秒一批，`isSessionFinal=true` 为末批）

**结果字段**：`SpeechRecognitionResult.speakerIndex`（稳定零基说话人序号，-1=未分配/未知）、`secondarySpeakerIndexes`（重叠说话的其他人）、`speakerConfidence`（[0,1] 归属分数）、`utteranceId`；`SpeakerDiarizationResult` 含 `windowIndex / windowBeginTime / windowEndTime / isSessionFinal / speakerTurns / speakerCount`；降级时带 `degraded/degradedReason/degradedMessage`。

相关实现：鸿蒙 `asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets` 等；Android 测试 `DiarizationDemoInstrumentedTest.kt`；设计文档 `delivery/harmony-dingqiao/docs/MEETING_ASR_BOUNDARY_DESIGN.md`、`ANDROID_DIARIZATION_PARITY_20260916.md`。

### 2. 会议/长时转写模式

- 引擎参数 `recognizerMode = "long"`：会议/持续转写，不做周期性硬切
- 会话参数 `enableContinuousRecognition = true`：保持同一模型会话持续识别

### 3. 目标说话人 ASR（只转写指定注册人，多人在场过滤他人）

- **声纹校验模式**：会话 `extraParams` 中 `enableVoiceprintVerification=true` + `voiceprintIds=[已注册声纹ID]`，final 结果返回 `speakerSimilarity`（目标声纹相似度），由业务方按阈值决定取舍
- **目标说话人 VAD**：`enableSpeakerVad=true`（+ `speakerVadThreshold=0.35 / speakerVadWindowMs=1500 / speakerVadHopMs=500 / speakerVadConsecutiveBelow=2`），目标离场提前断句，非目标片段触发事件 `SPEAKER_VAD_REJECTED(22)`；运行时开关 `engine.setSpeakerVadEnabled(Boolean)`
- **通用层直接注入音色向量**：`AsrSession.setTargetSpeaker(embedding: FloatArray)`（配合 SpeakerEnroller 产出）
- 方案与实测：`asr/android/docs/Target_speaker.md`（误记率 54%→4%，RTF 0.053）；工程化 `docs/speaker/PIPELINE.md`
- 服务端/离线 CLI 工具（`asr/tools/speaker/`，Python）：
  - `01_enroll_target.py` 多段注册 → `target_embedding.npy`
  - `02_ts_asr_offline.py` 输入 wav 输出 `[target]/[other]` 标签转写
  - `03_eval.py`~`15_*.py` 各类评测脚本

> 注意：gRPC/WS 服务端目前**不支持**多人分离，多人能力只在端侧 SDK（diarization/目标说话人）与 CLI 工具中。

---

## 三、音色提取接口（声纹/说话人 embedding）

音色提取在仓库中的实现是**声纹（voiceprint）embedding 提取**，模型为 3D-Speaker **ERes2Net**（`eres2net.onnx`，约 38MB，输出 512 维向量），基于 sherpa-onnx `SpeakerEmbeddingExtractor`。

### 1. 端侧 SDK 声纹接口（Android/HarmonyOS 通用）

| 接口 | 说明 |
|---|---|
| `SpeechRecognizeSdk.preloadVoiceprintModel(): Boolean` | 按需预装声纹模型 eres2net.onnx（v0.2.7 起内置 AAR/HAR，自动解包到 setWorkPath） |
| `SpeechRecognizeSdk.registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult` | **注册/提取音色**：样本 16k/16bit/单声道 PCM 或 WAV，每段 3~8 秒，至少 1 段（建议多段），返回生成的 `voiceprintId`（status=0 成功） |
| `SpeechRecognizeSdk.deleteVoiceprint(voiceprintId): Boolean` | 删除本地声纹（不存在抛 `VOICEPRINT_NOT_FOUND`） |
| 会话参数 `enableVoiceprintVerification + voiceprintIds` | final 结果附带 `speakerSimilarity` |

错误码：`VOICEPRINT_REGISTER_FAILED(1002200020) / SAMPLE_COUNT(21) / SAMPLE_DURATION(22) / NOT_FOUND(24)`。
模型说明：`asr/android/docs/customer/DINGQIAO_VOICEPRINT_MODEL.md`。

### 2. 底层提取器（直接拿 512 维音色向量）

- Android 通用层 `com.amphion.asr.SpeakerEnroller`（`asr/android/sdk/src/main/java/com/amphion/asr/SpeakerEnroller.kt`）：
  ```kotlin
  SpeakerEnroller(modelPath = ".../eres2net.onnx", numThreads = 1).use { enroller ->
      val embedding: FloatArray = enroller.enroll(segments)  // 多段均值 + L2 归一，512 维
  }
  ```
- 鸿蒙 `SpeakerEnroller.ets`；底层为 sherpa-onnx `SpeakerEmbeddingExtractor(+Config)`
- CLI：`asr/tools/speaker/01_enroll_target.py`（注册音频 → target_embedding.npy）
- TTS 侧的"音色"仅为**预置音色列表**（`TextToSpeechApi.listVoices()` 返回 `VoiceInfo.voiceId`），不支持音色克隆/提取

---

## 四、结论速查表

| 需求 | 推荐接口 | 形态 | 位置 |
|---|---|---|---|
| 语音转文字（服务器） | `asr.v1.AsrService.Recognize` | gRPC 双向流 | `asr/server/`（API.md + asr.proto） |
| 语音转文字（服务器，轻量） | WebSocket start/PCM/stop | WS + JSON | `asr/ws-server/` |
| 语音转文字（端侧离线） | `SpeechRecognizeSdk.createEngine → startListening/writeAudio/finish` | Android/HarmonyOS/iOS SDK | `asr/android|harmony|ios/` |
| 多人转写（分离所有人） | `StartParams.speakerDiarization=SpeakerDiarizationConfig(maxSpeakers≤4)` + `onSpeakerDiarizationUpdate/Result` | 端侧 SDK，完全离线 | `asr/android/sdk`、`asr/harmony/sdk` |
| 多人转写（只要指定人） | `enableVoiceprintVerification + voiceprintIds` / `enableSpeakerVad` / `AsrSession.setTargetSpeaker` | 端侧 SDK | 同上 + `asr/tools/speaker/` |
| 多人转写（离线批量文件） | `02_ts_asr_offline.py`（[target]/[other] 转写） | Python CLI | `asr/tools/speaker/` |
| 音色提取/注册 | `SpeechRecognizeSdk.registerVoiceprint(VoiceprintRegisterParams)`；底层 `SpeakerEnroller.enroll()`（eres2net，512 维） | 端侧 SDK | 模型 `eres2net.onnx` 内置 |

---

## 五、腾讯云 H20 生产服务器实况与三接口实测（2026-09-29，Phase 0 已验证）

> 服务器：`106.52.52.196`（ubuntu，H20 96GB，SSH 密码见上下文）。以下内容为**实地核查 + 亲自冒烟验证**的结果，与本文前四章（GitHub 仓库源码调研）互补：**Mac 端接入不需要自建 AmphionRuntime，直接走 amphion.top 公网 API 即可。**

### 5.1 现行生产拓扑（关键事实）

- **网关已容器化**，`docker compose` 单镜像 5 容器（`amphion-api-gateway`，代码在 `/home/ubuntu/amphion_api_gateway_service`）：
  - `amphion-gateway-e4f878e-a/b`（`python -m src.main`）→ 宿主机 `127.0.0.1:18910/18911`，nginx `amphion_gateway_pool` 指向它们
  - `amphion-portal-8ee6-a/b`（`portal.main`，Portal 前端/管理后台）→ `18112/18113`
  - `amphion-worker`（`src.worker_main`，后台任务：voice_sync 音色同步、capture 清理、临时凭证清理等）
- **systemd 的 `amphion_gateway.service` / `tts_stream_coordinator` / `tts_stream_worker` 均为历史归档方案**（`docs/runtime_workers.md` 明确"当前生产不要据此切换或重启"），8888 端口已废弃。**不要拉起它们**。
- 语音上游（`.env.compose` + `/health` 实测）：
  - 流式 ASR：`ws://172.16.0.4:8907/transcribe-streaming`（**本机** `qwen3-asr-vllm.service`，Qwen3-ASR-1.7B vLLM，GPU 0.20≈19.5GB；核查时停用，**已由本次行动拉起**，vLLM 加载约 1 分钟）
  - 非流式 ASR：`http://172.16.0.7:8001`（asr-remote-7，healthy）
  - **TTS：`http://172.16.0.2:8091`(qwen-tts-0.6b) / `:8092`(qwen-tts-1.7b) + 火山 Seed-ICL 2.0 音色复刻，全部 healthy**（本机 `/data/models/Qwen3-TTS-12Hz-0.6B-Base/` 与 `tts_streaming_service` 为旧方案遗留，未在现行链路中）
  - target-dialogue 说话人引擎：`http://172.16.0.3:8082`（audiollm provider，实测 `status: ready`）
- 测试 API Key（`.env.asr-public-test`，用户 sub=6，余额可用）：`sk-****`（联调 Key 请向团队索取，勿提交到仓库）
- 公网入口（本地 Mac 已实测可达）：`https://amphion.top`（nginx→网关容器），Portal 管理后台 `https://portal.amphion.top`。`asr.makaw.cn/api/stream` 为旧文档地址，现行统一走 `amphion.top`。

### 5.2 接口① Mac 流式转写（停顿修正）— ✅ 实测通过

`WS wss://amphion.top/asr/v1/realtime?api_key=sk-xxx`（服务器侧等价 `ws://127.0.0.1:18910/...`）。协议为 **OpenAI Realtime 风格**（与 `Qwen3_ASR_Streaming_API.md` 的 `END` 文本帧协议不同，以本节为准）：

```jsonc
// C→S 可选配置
{"type": "session.update", "session": {"language": "auto"}}
// C→S 音频（base64 PCM 16k/16bit/mono，建议 100ms=3200B 一帧）
{"type": "input_audio_buffer.append", "audio": "<base64>"}
// C→S 用户停止说话/松键
{"type": "input_audio_buffer.commit", "final": true}
```
S→C 事件：`session.created` → `transcription.delta`（**每个 delta 都带全量累积 `text` 字段**，VAD 分段后后段会整段替换修正前段）→ `transcription.done`（最终全文 + `usage.seconds` 计费）。
**"停顿修正"实现方式：前端每次收到 delta 就用其 `text` 全量覆盖显示**（实测 6s 粤语音频："…从电影《阿妈的情书》正在热播。" → 修正为 "电影《阿妈的情书》正在热播当中。"）。网关内置 Silero VAD + pacer（10s 缓冲上限），发送速率约 5 倍实时仍正常。

### 5.3 接口② 多人说话人分离 — ✅ 实测通过

1. **声纹注册** `POST /speaker/v1/profiles`（`-F display_name=... -F consent=true -F audio=@xxx.wav`；consent 字段强制，合规审计）→ 返回 `{"id":"spk_…","status":"ready","quality":{…}}`（实测成功，网关内部自动切段评估音质）。
2. **签发一次性 Token** `POST /auth/v1/ephemeral-tokens` `{"resource":"asr.target_dialogue"}` → JWT `access_token`（生产已签发 888 次）。
3. **对话 WS** `WS /asr/v1/target-dialogue`，鉴权二选一（均实测通过）：首帧 `{"type":"session.authenticate","access_token":"…"}`，或 `?api_key=` query。
   - 首条配置必须 `session.update`：`{"session":{"filter":{"mode":"open"},"participants":[],"audio":{"sample_rate_hz":16000},"recognition":{"mode":"role_separation"}}}`；`targets_only` 模式则 `participants` 必填（每项含 `profile_id`），用于过滤旁人。
   - 音频：**二进制 PCM 帧**（= append），结束发 `{"type":"input_audio_buffer.commit"}`。
   - 事件（实测）：`session.created` → `transcription.partial`（`speaker_name:"正在确认说话人"`, `anonymous:true`）→ `transcription.final`（**`role_index`、`speaker_name:"说话人 N"`、`start_ms/end_ms`**）→ `speaker.sample.progress`（声纹采样进度，满 5s 可 enroll）→ `session.done`（`identified_roles/suppressed_roles` 统计）。
   - open 模式下可用 `speaker.enroll` 消息把当前 `role_index` 在会话中升级为命名参与者；还支持热词 `session.hotwords`、可选翻译/情绪/TTS（`translation_plugins:"qwen_text"` 等，DAG 引擎）。

### 5.4 接口③ 声纹注册 → 音色克隆 — ✅ 实测通过

1. `POST /tts/v1/audio/voices`（`-F voice_name=xxx -F audio_file=@ref.wav`，2~15s 参考音频；**每用户上限 10 个音色**，超限需 `DELETE /tts/v1/audio/voices/{name}`）→ 同步复刻，返回 `status:"ready"`；内部：火山 **Seed-ICL 2.0**（`speaker_id/train_status/slot_status`）+ 同步到 172.16.0.2 TTS 后端（`u{user_id}_{voice_name}`），`ref_text` 自动 ASR。
   - 实测：上传 2s 英文童声 → `ref_text:"Kids are talking."`，音色名 `gaojiao_test`（保留在测试账号中供验收复用）。
2. `POST /tts/v1/audio/speech`（JSON：`model:"qwen-tts-0.6b"`, `input:"文本"`, `voice:"gaojiao_test"`, `response_format:"wav"`）→ **实测 HTTP 200，24kHz/16bit/mono WAV，132KB/1.03s**。A 上传音色→用 A 的 voice 合成 B 的文本即"克隆"，链路成立。

### 5.5 下一步（Phase 1–3）

- Phase 1：Mac 管理页接入接口①（注意用最新 `transcription.delta.text` 全量覆盖；计费按 `usage.seconds`）。
- Phase 2：接口② open 模式起步；targets_only 模式需先走 profiles 注册（多设备声纹一致时用同一 profile）。
- Phase 3：接口③ 验收脚本可直接复用本节 curl 序列；如需正式业务 Key，走 Portal（portal.amphion.top）注册/控制台创建，或由网关管理员在 DB/控制台签发。
- 冒烟脚本存档：`gaojiao/smoke_asr.py`（接口①，含协议注释）、`gaojiao/smoke_target_dialogue.py`（接口②双鉴权尝试）。服务器侧副本 `/tmp/smoke_asr.py`、`/tmp/smoke_td.py`。

