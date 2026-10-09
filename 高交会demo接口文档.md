# 高交会demo：腾讯云 H20 接口暴露与本地接入

> 服务器名称：**VM-0-4-ubuntu**（腾讯云 H20 GPU 云主机，公网 IP `106.52.52.196`，SSH `ubuntu@106.52.52.196`）
> 网关实现：`amphion-api-gateway`（Docker 单镜像 5 容器，gateway 实例 `amphion-gateway-e4f878e-a/b` 监听宿主机 `127.0.0.1:18910/18911`，代码目录 `/home/ubuntu/amphion_api_gateway_service`）
> 公网入口：**`https://amphion.top`**（宿主机 nginx 443 → `amphion_gateway_pool`）——三类接口**已经通过该域名对公网暴露**，本地端无需在服务器做任何改动
> 文档日期：2026-09-29；三类接口均已在本地 Mac 实测跑通

---

## 一、暴露方式总览

| 方式 | 地址 | 适用场景 | 状态 |
| --- | --- | --- | --- |
| 公网直连 | `https://amphion.top` / `wss://amphion.top` | Mac 端日常开发联调、后台管理页、生产接入 | 已实测 |
| SSH 隧道（备用） | `ssh -N -L 18910:127.0.0.1:18910 ubuntu@106.52.52.196`，然后本地用 `http://127.0.0.1:18910` / `ws://127.0.0.1:18910` | 公网 DNS/证书异常时绕过 nginx 直连网关容器 | 备用 |
| 服务器内自测 | `http://127.0.0.1:18910`（gateway-a）、`http://127.0.0.1:18911`（gateway-b） | 服务器侧排障 | 已实测 |

> 注意：老文档里的 `asr.makaw.cn/api/stream`（`END` 文本帧协议）与 systemd `amphion_gateway.service`（8888 端口）均为**历史归档方案**，现行统一走 `amphion.top`，协议见下文。

## 二、接口绝对路径

三类接口共 8 个端点，鉴权统一用 API Key（`X-API-Key` 请求头，或 WS 用 `?api_key=` 查询参数）。

### 接口① Mac 流式转写（含停顿修正）

| 方法 | 绝对路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `WSS` | `wss://amphion.top/asr/v1/realtime?api_key=<KEY>` | api_key | 流式转写主端点，OpenAI Realtime 风格 |
| `GET` | `https://amphion.top/asr/health` | `X-API-Key` | ASR 链路健康检查 |

消息流：`session.update`（可选，`{"language":"auto"}`）→ `input_audio_buffer.append`（`audio`=base64 PCM，16kHz/16bit/mono，建议 100ms=3200B/帧）→ 停止说话发 `{"type":"input_audio_buffer.commit","final":true}`。
返回事件：`session.created` → `transcription.delta`（**每个事件都带全量累积 `text`，停顿后整段修正，前端直接覆盖显示**）→ `transcription.done`（最终全文 + `usage.seconds` 计费）。

### 接口② 多人说话人分离

| 方法 | 绝对路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `POST` | `https://amphion.top/speaker/v1/profiles` | `X-API-Key` | 声纹注册（multipart：`display_name`、`consent=true`、`audio`） |
| `POST` | `https://amphion.top/auth/v1/ephemeral-tokens` | `X-API-Key` | 签发一次性 JWT（`{"resource":"asr.target_dialogue"}`），供浏览器 WS 免带长期 Key |
| `WSS` | `wss://amphion.top/asr/v1/target-dialogue` | 首帧 `session.authenticate` 或 `?api_key=` | 多人分离对话流（open=匿名分离所有人 / targets_only=只留注册人） |

WS 首条配置必须是 `session.update`：`{"session":{"filter":{"mode":"open"},"participants":[],"audio":{"sample_rate_hz":16000},"recognition":{"mode":"role_separation"}}}`；音频用**二进制 PCM 帧**（= append）；结束发 `input_audio_buffer.commit`。
返回事件：`transcription.partial`（"正在确认说话人"）→ `transcription.final`（含 `role_index`、`speaker_name`、`start_ms/end_ms`）→ `speaker.sample.progress`（声纹采样满 5s 可 `speaker.enroll` 命名）→ `session.done`（`identified_roles/suppressed_roles` 统计）。

### 接口③ 声纹注册 → 音色克隆

| 方法 | 绝对路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `GET` | `https://amphion.top/tts/v1/audio/voices` | `X-API-Key` | 当前用户音色列表 |
| `POST` | `https://amphion.top/tts/v1/audio/voices` | `X-API-Key` | 上传 2~15s 参考音频同步复刻（multipart：`voice_name`、`audio_file`），每用户上限 10 个 |
| `DELETE` | `https://amphion.top/tts/v1/audio/voices/{voice_name}` | `X-API-Key` | 删除音色（腾配额） |
| `POST` | `https://amphion.top/tts/v1/audio/speech` | `X-API-Key` | 合成：`{"model":"qwen-tts-0.6b","input":"文本","voice":"音色名","response_format":"wav"}`，返回音频字节 |

辅助端点：`GET https://amphion.top/health`（网关总健康：TTS/ASR/E2V 后端状态、ephemeral_auth 统计）；`https://portal.amphion.top/`（Portal 管理后台，注册账号、签发正式 API Key）。

## 三、鉴权与 Key 管理

- 公共测试 Key（联调用，账号 sub=6）：`sk-****`（请向团队索取，通过环境变量 `AMPHION_API_KEY` 或页面输入框提供，勿写入代码）
  - 环境变量方式：`export AMPHION_API_KEY=sk-...`（`local_demo.py` 自动读取）
- 正式业务 Key：到 `https://portal.amphion.top` 注册账号后在控制台创建，勿在生产长期使用公共测试 Key。
- 浏览器/WS 场景：先 `POST /auth/v1/ephemeral-tokens` 换一次性 JWT（默认 120s），WS 首帧 `{"type":"session.authenticate","access_token":"..."}`，避免长期 Key 暴露在前端。

## 四、快速开始（Mac 本地）

### 4.1 环境准备与样例音频

```bash
pip3 install --user websockets     # 仅 WS 类命令需要

# 生成 16kHz/16bit/mono 测试音频（macOS 自带 say/afconvert，也可用任意 wav）
say -o /tmp/demo.aiff "今天天气不错，我们一起测试语音接口。"
afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/demo.aiff gaojiao/sample_zh_16k.wav
```

### 4.2 一键交互：`gaojiao/local_demo.py`（覆盖三类接口 8 个命令）

```bash
cd gaojiao

python3 local_demo.py health                          # 健康检查
python3 local_demo.py asr sample_zh_16k.wav           # ①流式转写（打印 partial→final）
python3 local_demo.py token                           # ②签发一次性 token
python3 local_demo.py enroll sample_zh_16k.wav 张三   # ②声纹注册
python3 local_demo.py dialogue sample_zh_16k.wav      # ②多人分离（open 模式）
python3 local_demo.py voices                          # ③音色列表
python3 local_demo.py clone sample_zh_16k.wav my_voice          # ③参考音频→复刻音色
python3 local_demo.py speak "你好，克隆测试。" my_voice out.wav # ③克隆合成
```

### 4.3 网页交互 Demo（推荐，图形界面）

浏览器版三类接口一体化 Demo（`gaojiao/demo_server.py` + `gaojiao/demo.html`，零依赖、零构建）：

```bash
cd gaojiao
python3 demo_server.py        # 仅 Python 3 标准库
# 浏览器打开 http://localhost:8765/
```

三个 Tab 对应三类接口，全部走公网真实链路：

| Tab | 交互 | 说明 |
| --- | --- | --- |
| 一 流式转写 | 麦克风实时 / 音频文件测试，大字实时上屏，结束出全文与计费 | 展示"停顿修正"：delta 为全量累积文本，直接覆盖渲染 |
| 二 多人分离 | 麦克风/文件 → 说话人气泡流（按 `role_index` 着色） | 自动优先申请 ephemeral token，失败自动退回 `?api_key=` |
| 三 声纹克隆 | 录 2-15s 参考音频（带波形图）、注册复刻音色、列表/删除、文本合成播放 | multipart 上传走本地代理 |

实现要点（为何需要本地小服务器）：
- **网关未开 CORS**（无 `Access-Control-Allow-Origin`，预检 405）→ 浏览器 HTTP 请求（token/voices/speech）由 `demo_server.py` 的 `/proxy/*` 同源转发到 `https://amphion.top`；
- **WS 不受 CORS 限制** → 接口①②由浏览器直连 `wss://amphion.top`（音频管线：Web Audio 采集/重采样到 16k s16le，①发 JSON base64 帧、②发二进制帧，均 100ms/帧）；
- API Key 在页面顶栏输入，存 `localStorage`；关闭服务器 `Ctrl+C` 即可，不留任何后台服务。

### 4.4 curl 等价（接口③，无任何依赖）

```bash
KEY='sk-****'  # 运行前 export AMPHION_API_KEY=sk-... 或替换为你自己的 Key

curl -s -H "X-API-Key: $KEY" https://amphion.top/tts/v1/audio/voices

curl -s -X POST https://amphion.top/tts/v1/audio/voices \
  -H "X-API-Key: $KEY" -F 'voice_name=my_voice' -F 'audio_file=@sample_zh_16k.wav'

curl -s -X POST https://amphion.top/tts/v1/audio/speech \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"qwen-tts-0.6b","input":"任意文本","voice":"my_voice","response_format":"wav"}' \
  -o out.wav
```

## 五、验证状态（2026-09-29 实测）

| 接口 | 验证内容 | 结果 |
| --- | --- | --- |
| ① | 公网 WS 全流程，partial→停顿修正→final+计费 | 成功 |
| ② | profiles 注册（`spk_14cda947...` ready）、token 签发、open 模式 WS 双鉴权 | 成功 |
| ③ | 上传复刻（火山 Seed-ICL 2.0）、克隆合成 WAV / 约 1s | 成功（测试音色 `gaojiao_test` 已留在账号内） |

服务器侧依赖：流式 ASR 上游 `qwen3-asr-vllm.service`（端口 8907）已于本次行动拉起并保持 `active`；TTS 后端在内网 `172.16.0.2:8091/8092`，无需本机维护。

## 六、接入计划（后续阶段）

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| Phase 1 | Mac 管理页接入接口①：录音→`append`→松键 `commit`→用 `delta.text` 全量覆盖渲染 | partial 流畅，停顿后文本被修正，`done` 后稳定 |
| Phase 2 | 接入接口② open 模式（匿名 `说话人 1/2/...`）；需过滤旁人时再走 profiles + `targets_only` | 两人对话各语句正确归属 `role_index` |
| Phase 3 | 接入接口③：本机录音 2~15s → `clone` → `speak` 任意文本 | A 的音色读出 B 的文本，主观可辨相似度 |

## 七、注意事项与限制

- **计费**：接口①按 `usage.seconds`（音频时长）计费，WS 建立时有余额预检，余额不足连接以 4002 关闭。
- **音频规格**：一律 16kHz/16bit/单声道 PCM；接口① JSON base64 帧，接口② 二进制帧；网关 pacer 缓冲上限 10s，按近实时速率发送即可。
- **音色配额**：每用户 10 个音色，超限先 `DELETE /tts/v1/audio/voices/{name}`。
- **合规**：接口②声纹注册强制 `consent=true`（服务器记录 `consent_recorded_at` 审计字段）。
- **后端真相**：TTS 克隆走火山 Seed-ICL 2.0 + 内网 Qwen-TTS 后端（`172.16.0.2`），**不要**在 106.52.52.196 上重启旧的 `tts_stream_coordinator/worker` 或 `amphion_gateway.service`（8888），它们是归档方案。
- 脚本存档：`gaojiao/local_demo.py`（本地公网直连 CLI）、`gaojiao/demo_server.py` + `gaojiao/demo.html`（本地网页交互 Demo）、`gaojiao/smoke_asr.py`、`gaojiao/smoke_target_dialogue.py`（服务器内网版）。
