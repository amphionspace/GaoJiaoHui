# 中文本人声音克隆：先试听再接入

核对日期：2026-10-19。免费额度与账号、地域和活动有关，以控制台实际显示为准，不代表长期免费。

| 服务 | 能力 | 试用条件 |
| --- | --- | --- |
| 阿里云百炼 CosyVoice | 中文短录音音色复刻，可合成未来回信；优先试听 | 北京地域相关模型有 10,000 字符合成免费额度，有效期 90 天。中文按计费字符规则折算，不等于一万汉字。 |
| 硅基流动 CosyVoice | 约 8–10 秒参考录音，音色 URI 或动态参考音频 | 复刻需实名；合成按量计费，不把注册赠金承诺为永久免费。 |
| ElevenLabs | 即时音色克隆，跨语种生成 | 免费套餐不含即时克隆；需要 Starter 或更高套餐。 |

官方依据：[百炼音色复刻](https://help.aliyun.com/zh/model-studio/qwen-tts-voice-cloning)、[百炼定价](https://help.aliyun.com/zh/model-studio/model-pricing)、[硅基流动](https://docs.siliconflow.cn/docs/userguide/capabilities/text-to-speech)、[ElevenLabs 套餐](https://elevenlabs.io/pricing)。

当前仓库已接入百炼的 Qwen Omni 声音复刻链路：第一步自然讲述自动采集 10–15 秒清晰录音，服务端调用 `qwen-voice-enrollment` 创建临时音色，再用同一个 Omni 模型生成未来回信。它与原来本地 Qwen3-TTS 1.7B 的接口不同，不能把百炼地址直接填进 `JOURNEY_TTS_URL`；本地启动脚本已选择百炼适配器。参考录音只用于克隆音色，真正播放的内容仍是未来回信。

建议用安静环境下约 10–15 秒的本人自然讲话试听，再合成下面的样例。不同于参考录音的合成文本是检验克隆的必要步骤，但产品仍从第一步自然讲述自动采样，不要求另读指定文字。

> 我是以后的你，想陪今天的你聊几句。你提到想让爸爸搬东西轻松一点，我记下了这份惦记。不用今天就找到全部答案，先问一个最在意的问题，也是在往前走。

判断顺序：是否像本人、普通话是否自然、情绪是否克制、首句等待多久、长句是否漏字、是否能删除临时音色。不要只比较固定播音员试听。

2026-10-20 已用合成测试录音完成真实“上传样本→创建临时音色→合成→删除”验证，并在浏览器中验证自动播放。修复了上传依赖、音色名称长度和本地编号与百炼编号的映射问题。测试音色已清理，百炼密钥仅放服务端；仍需本人录音确认音色相似度。详细记录见 `docs/validation/journey-2026-10-20.md`。

## 自建 TTS 优先 + 百炼兜底（2026-11-02）

合成链路改为两级：

1. 访客录音样本在音色注册时由服务端留一份 5–30 秒参考音（`.journey-state/tts/`，默认 2 小时、最多 40 条，音色删除时一起删除）。
2. 合成先调自建 TTS：`https://test-playground.amphion.top/tts-api/v1/audio/speech`，用 `ref_audio` + `x_vector_only_mode` 复刻访客音色，`language` 跟随页面中英文。
3. 自建超时、非 200 或返回不是 WAV 时，自动降级到百炼已注册的 `voice`。
4. 自建失败后进入 30 秒冷却，避免每个请求都先等一次超时；冷却期内直接走百炼。

配置：

```ini
JOURNEY_TTS_ORDER=amphion,bailian     # 只写 bailian 可关闭“自建优先”
AMPHION_TTS_URL=https://test-playground.amphion.top
AMPHION_TTS_TIMEOUT=45                # 自建单次合成超时
AMPHION_TTS_COOLDOWN=30               # 自建失败后的冷却秒数
JOURNEY_TTS_SAMPLE_TTL=7200           # 参考音缓存秒数
JOURNEY_TTS_SAMPLE_MAX=40             # 参考音缓存条数
```

排障：

- `/admin` 的“旅程阶段”新增 `自建TTS成功`、`自建TTS失败`、`无参考音`、`降级百炼`、`百炼成功`、`百炼失败`。
- `/api/health` 的 `checks.tts` 返回 `provider`（如 `amphion → bailian`）、`amphion_ready`、`amphion_ms`、`cooldown`；`/tts-api/ready` 的结果缓存 20 秒。
- 服务日志会打印 `amphion tts failed: <类型或状态码>`，不包含朗读文本。
- 文本侧同时清理“AI 合成 / 情景演示 / 虚构台词 / 仅供演示”等说明性话术，避免被 TTS 读出来。
