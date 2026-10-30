# 后台看板与服务监控

运维入口：`https://amphion-gjh.amphiondev.com/admin`。默认只统计聚合数据，不记录密钥或后台密码；计数在服务重启后归零。可选的“会话记录”开启后会保存讲述、手记、访客参考音与回信语音（**不保存完整录音**），保留期与开关见下文。

## 组成

| 组件 | 位置 | 作用 |
|---|---|---|
| 看板页面 | `/admin`（Basic 认证） | 服务/依赖状态、请求量、旅程阶段、时延、接口、最近错误 |
| 看板数据 | `/api/admin/stats`（Basic 认证） | 页面每 10 秒拉取的 JSON |
| 总汇 | `/api/admin/summary`（Basic 认证） | 今日体验、总体验、已生成、已打印、异常 |
| 会话记录 | `/api/admin/sessions`（Basic 认证） | 每条讲述的原文、手记、耗时与音频 |
| 指标 | `/metrics`（Basic 认证） | Prometheus 文本格式，含健康 gauge 与磁盘比例 |
| 健康探针 | `/api/health` | 供负载均衡、监控与人工排查使用；返回 `status/checks/stats` |
| 告警任务 | `journey-monitor.timer` | 每分钟检查一次，异常/恢复推企业微信群机器人 |

## 账号与访问

后台账号放在 `/etc/amphion-gjh/admin.env`（`600 root:root`），由 systemd 注入应用：

```ini
JOURNEY_ADMIN_USER=admin
JOURNEY_ADMIN_PASSWORD=<长随机密码>
# 可选：只允许指定公网 IP（逗号分隔）
# JOURNEY_ADMIN_IPS=203.0.113.10
```

修改后 `systemctl restart amphion-gjh`。未配置账号时 `/admin` 与 `/metrics` 返回 503，不会暴露数据。

- 认证方式为 HTTP Basic，必须走 HTTPS。
- 经 Caddy 反代时应用看到的来源是 `127.0.0.1`，此时才会采信 `X-Forwarded-For` 的第一个地址做白名单判断。
- 浏览器会缓存 Basic 凭据；改密码后关掉浏览器或换无痕窗口再登录。

## 看板怎么读

- **总汇**：顶部五张卡片——今日体验、总体验、已生成（有手记）、已打印（点过打印并触发 `afterprint`）、异常（未生成出文字）。
- **服务 / 依赖**：服务总体、前端构建、文本模型（是否配置、模型名）、语音识别（托管凭证/网关密钥）、声音合成（提供方）、磁盘（使用率与剩余空间，>=95% 标红）。
- **请求**：服务启动后的接口请求总数、5xx 数、最近 5 分钟请求与错误。健康探针和管理接口不计入，避免监控自己刷高计数。
- **旅程阶段**：`草稿上屏`、`审校完成`、`审校回退`、`整理失败`、`语音会话`、`插画请求/失败`。
- **阶段时延**：草稿与终版的 P50/P95/最近一次，来自服务端实际阶段耗时。
- **接口表**：按路径统计次数、5xx、P50/P95。流式接口 `compose/stream` 的时延是**首字节**，不代表整段生成耗时，看“阶段时延”更准确。
- **最近错误**：最近 40 条，只有时间、路径、状态码、错误码，不含任何正文。

## 会话记录（可选）

看板里的“最近会话”用于现场复盘：某位访客说了什么、生成了什么手记、各阶段用了多久。默认关闭，当前线上已开启。

配置 `/etc/amphion-gjh/session.env`（`600 root:root`），修改后 `systemctl restart amphion-gjh`：

```ini
JOURNEY_SESSION_LOG=1                 # 1 开启会话记录；0 完全关闭
JOURNEY_SESSION_TRANSCRIPT=1          # 1 保存讲述原文；0 只保存手记/回信，不存原文
JOURNEY_SESSION_RETENTION_DAYS=7      # 1-90 天，插入时自动清理过期记录
JOURNEY_SESSION_MAX=500               # 最多保留条数
JOURNEY_SESSION_AUDIO=1               # 1 保存访客参考音与回信语音
JOURNEY_SESSION_AUDIO_MAX=120         # 最多保留多少条带音频的会话
```

- 存储：会话在 `/.journey-state/sessions.sqlite3`，音频在 `/.journey-state/audio/`（与音色状态同目录，权限 600）。**不保存完整录音**：只保存注册音色用的 5–30 秒参考音，以及生成的回信语音。
- 一条记录包含：访客编号（用户1、用户2…）、时间、主题、讲述原文（可关闭）、手记、回信、关键词、模型、草稿/终版耗时、是否完成审校、是否打印。
- 展开一条记录可以播放“访客参考音”和“回信语音”；音频按 `JOURNEY_SESSION_AUDIO_MAX` 保留最近的若干条，超出后自动删除最旧的文件。
- 看板里点击任意一条可展开原文、手记、回信与音频；“清空”按钮会删除全部会话记录和音频文件，删除前有确认。
- 记录只通过 `/api/admin/sessions` 暴露，需要后台 Basic 认证；服务端写入失败不会影响访客拿到手记。
- 隐私建议：展期结束或移交设备前，用“清空”按钮删除记录与音频；不需要复盘时把 `JOURNEY_SESSION_LOG=0` 并重启。参考音与回信语音都可用于识别说话人，按与讲述同等级别保管。

## 告警

`journey-monitor.timer` 每分钟运行 `journey-monitor.service`，读取本机 `/api/health`：

- 任一检查项 `ok=false`，或健康接口不可达 → 告警；
- 恢复后发送一次“已恢复”；
- 同一项持续异常时每 10 分钟提醒一次，避免刷屏；
- 磁盘阈值 95%。

配置 `/etc/amphion-gjh/monitor.env`（`600 root:root`）：

```ini
JOURNEY_MONITOR_URL=http://127.0.0.1:8766/api/health
JOURNEY_MONITOR_STATE=/var/lib/amphion-gjh/monitor.json
JOURNEY_PUBLIC_URL=https://amphion-gjh.amphiondev.com/
JOURNEY_ALERT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<群机器人 key>
```

- webhook 是私密地址：不要提交 Git、不要贴进聊天。留空时只记录状态，不发送。
- 修改后无需重启应用，下一次 timer 自动生效。
- 常用命令：

```sh
systemctl status journey-monitor.timer
systemctl start journey-monitor.service          # 立即执行一次
journalctl -u journey-monitor.service -n 50      # 查看最近一次结果
sudo -u amphion-gjh /usr/bin/python3 /opt/amphion-gjh/bin/journey-monitor.py --dry-run
```

`--dry-run` 只打印当前检查结果，不发送、不写状态文件。

## 部署与更新

1. 同步 `server/`（含 `metrics.py`、`monitor.py`、`sessions.py`），构建前端不需要重跑。
2. `install -m 644 deploy/journey-monitor.service /etc/systemd/system/`，同样安装 `.timer`。
3. 首次创建 `/etc/amphion-gjh/admin.env`、`monitor.env`、`session.env`（参考 `.example`，权限 600）。
4. `install -m 755 server/monitor.py /opt/amphion-gjh/bin/journey-monitor.py`，目录属主 `amphion-gjh`。
5. 给 `amphion-gjh.service` 的 drop-in 增加两条 `EnvironmentFile=`：`admin.env` 与 `session.env`。
6. `systemctl daemon-reload && systemctl restart amphion-gjh && systemctl enable --now journey-monitor.timer`。

监控脚本独立于 release 目录，升级版本时不用改 unit；应用侧只依赖 `server/metrics.py` 与新增路由。

## 常见问题

- **打开 `/admin` 提示 401**：浏览器缓存的旧密码；关闭浏览器或换无痕窗口。
- **503 后台未启用**：`admin.env` 未创建或没有加进 drop-in。
- **磁盘一直标红**：当前根分区使用率 98%，阈值 95%。清理旧 release / Docker 镜像或扩容后自动恢复。
- **计数看起来很小**：计数随服务重启归零，属于预期；长期趋势应接 Prometheus 抓 `/metrics`。
