# 未来来电 demo1 · Amphion 语音电话亭

Vue 3 前端与 FastAPI 后端，包含未来手记旅程、多人对话工作台、声音克隆对话。

未来手记使用完整讲述生成摘要与来自未来自己的回信；在第一次自然讲述中采集参考声音，不要求用户去另一模块重录。声音必须来自本次已注册音色，失败时保留手记并明确提示，不回退到系统机械人声。

## 当前交付状态

2026-10-21：**demo1 已上线**：[HTTPS 体验地址](https://amphion-gjh.amphiondev.com/)，分支为 `codex/demo1`。包含红色写实电话首页、竖屏适配、50 字以内的未来回信、首次讲述采集声音、打印手记、会话取消与失败重试。其他工作台和已有修改保留。线上部署状态与验收范围见 [demo1 发布记录](docs/DEMO1.md)。

**TTS 已接入百炼适配器，但仍需用本人录音试听验收音色相似度。** 本地启动脚本会使用百炼作为未来手记的 TTS 提供方；原网关兼容协议仍保留，可通过 `JOURNEY_TTS_PROVIDER=legacy` 切回。特定型号打印机的出纸反馈也尚未接入，目前使用浏览器原生打印。详见 [交付检查](docs/DELIVERY.md) 和 [TTS 试用选择](docs/TTS-OPTIONS.md)。

## 安装与启动

使用 Node.js 22.12+、Python 3.11。本机既有 Python 3.9 环境也可运行本轮代码。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
npm --prefix frontend ci
.venv/bin/python scripts/run_local.py
```

浏览器打开 <http://127.0.0.1:5173/>。启动脚本统一运行前端 5173 与后端 8767；任一端退出即停止另一端，端口被占用时明确报错，不悄悄换入口。终端退出或电脑休眠后本地服务会停止，重新运行该脚本即可。

生产使用构建产物，由后端单端口提供：

```sh
npm --prefix frontend run build
HOST=127.0.0.1 PORT=8766 .venv/bin/python -m server.main
```

生产入口需 HTTPS 反向代理，才能让非 localhost 浏览器使用麦克风。不要将 Vite 开发服务器作为公网服务。

## 配置

- 右上角“连接设置”允许体验者填写自己的语音网关密钥，保存在当前浏览器，刷新后保留；不得写入仓库或前端构建。它不是服务器登录密码，也不是百炼或 DeepSeek 的服务端密钥。
- 文本模型使用根目录 `.env.journey.json`，字段为 `url`、`model`、`api_key`，结构见 [示例](server/journey-config.example.json)。该文件被 Git 忽略，建议权限 600。不要把实际密钥发到聊天或提交记录中。
- 也可使用 `JOURNEY_LLM_URL`、`JOURNEY_LLM_MODEL`、`JOURNEY_LLM_API_KEY`，环境变量优先；模型配置每次请求读取。
- 百炼 TTS 使用根目录 `.env.bailian.json`，保存业务空间、北京地域地址和服务端 API Key，文件被 Git 忽略且应为权限 600。当前适配 `qwen-voice-enrollment` 创建临时音色，再用同一 `qwen3.5-omni-plus` 模型流式合成本人声音；密钥不会下发到浏览器。
- `JOURNEY_TTS_PROVIDER=bailian` 启用百炼适配器，`JOURNEY_TTS_PROVIDER=legacy` 使用原有 `/v1/audio/voices` 网关协议。提供方只影响未来手记 TTS，不改变 ASR 与文本接口。
- 语音 HTTP/WS 地址见 [运行配置示例](deploy/runtime.env.example)。前端启动时读取 `/api/config`，不需要为换网关重新构建。
- Demo1 支持全界面英文体验：打开 `?lang=en`，或在页面右上角切换 `EN / 中`。竖屏英文地址为 `?view=portrait&lang=en`。
- `JOURNEY_TTS_URL` 指向兼容当前临时音色协议的服务；**不能直接填任意商业厂商 URL**，注册、合成和认证协议需要适配。
- `/api/journey/compose`（及前端实际使用的流式版本 `/api/journey/compose/stream`）与百炼声音接口必须携带有效 `X-API-Key`，通过网关临时令牌接口校验。可设置服务端 `JOURNEY_ACCESS_KEY` 改为固定访问密钥校验；ASR 仍要求有效的网关密钥。

文本与百炼声音接口共用限流：每来源每分钟最多 30 次、每密钥每分钟 10 次。文本同时最多 2 次；单进程文本总并发最多 8 次。密钥哈希缓存 60 秒，错误响应不回显密钥或完整上游异常。限流是单进程方案，扩容前需改为共享存储。

- **运维看板**：`https://amphion-gjh.amphiondev.com/admin`（HTTP Basic，账号见服务器 `/etc/amphion-gjh/admin.env`）。展示服务与依赖状态、请求量、旅程阶段时延、接口统计和最近错误；Prometheus 指标在 `/metrics`。默认只统计聚合数据；可选的“会话记录”会把单次讲述、手记和回信语音保存在服务器（不保存完整录音），默认保留 7 天，开关与保留期见 [后台与监控](docs/ADMIN.md#会话记录可选)。看板顶部有今日体验/总体验/已生成/已打印/异常总汇。
- **告警**：`journey-monitor.timer` 每分钟检查 `/api/health`，异常与恢复推企业微信群机器人；webhook 配置在 `/etc/amphion-gjh/monitor.env`。接入与排障见 [后台与监控](docs/ADMIN.md)。

## 验证

```sh
npm --prefix frontend test
npm --prefix frontend run build
.venv/bin/python -m unittest discover -s server -p 'test_*.py' -v
```

真实模型质量检查是会消耗额度的手动命令；CI 不调用付费接口：

```sh
.venv/bin/python -m server.evaluate_journey --output docs/validation/llm-local.json
```

测试素材均为虚构，报告需人工阅读；关键词命中不能证明共情或完全忠实。当前报告见 [真实模型样例](docs/validation/llm-2026-10-19.json)。

`/api/health` 只代表本应用存活，不代表 ASR、LLM、TTS 全部正常。工作人员面板分别检查文本配置、声音状态；真正可用性必须通过生成与试听确认。

[生产部署与回滚](docs/DEPLOYMENT.md) · [手记流程与原部署记录](JOURNEY.md) · [历史 Demo 说明](docs/archive/README-demo.md)

主要入口在 `frontend/src/components/BoothJourney.vue`、`ModuleWorkbench.vue`、`ModuleVoiceClone.vue`。共享取消机制与播放队列在 `core/session.js`、`core/speechQueue.js`；文本生成及审校在 `server/journey_text.py`；代理与请求边界在 `server/main.py`、`server/security.py`。旧版单文件作为历史资料保留，不是当前发布入口。
