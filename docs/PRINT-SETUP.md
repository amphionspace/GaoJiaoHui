# 现场打印设置（静默打印）

电话亭的手记是 80 × 170 mm 的单页。点击「打印手记」后要**直接出纸、不弹打印对话框**，靠的是浏览器的 `--kiosk-printing` 参数 + 操作系统的默认纸张。网页本身无法跳过打印对话框，这是浏览器的安全限制。

页面里的打印样式固定在 `@page{size:80mm 170mm;margin:0}`，内容按 80 × 170 mm 排版。

---

## 一、macOS（Chrome）

### 1. 默认打印机

系统设置 → 打印机与扫描仪 → 选中 EPSON L3350 →「默认打印机」选它。

### 2. 建 80 × 170 mm 纸张

1. 任意网页按 ⌘P；
2. 纸张大小 →「管理自定纸张大小…」→ **+**；
3. 名称 `80x170`，宽 `80 mm`，高 `170 mm`，边距全部 `0`；
4. 选回该尺寸，点「预设」→「将当前设置存储为预设」，设为默认；
5. 系统设置 → 打印机与扫描仪 → 选中打印机 →「打印机设置 / 选项与耗材」，把默认纸张也改成 `80x170`。

### 3. 启动

```sh
chmod +x deploy/kiosk-print.command
./deploy/kiosk-print.command
```

脚本会先退出已开的 Chrome，再用独立配置目录带参启动：`--kiosk --kiosk-printing --user-data-dir=... <网址>`。

---

## 二、Windows（Chrome 或 Edge）

两者都是 Chromium 内核，参数相同，区别只是可执行文件名。

### 1. 默认打印机

设置 → 蓝牙和其他设备 → 打印机和扫描仪 → 选中 EPSON L3350 →「设为默认值」。

### 2. 建 80 × 170 mm 纸张

1. 控制面板 → 设备和打印机 → 点任意打印机 →「打印服务器属性」；
2. 「格式」选项卡 → 勾选「创建新格式」；
3. 名称 `80x170`，宽度 `8.0 cm`，高度 `17.0 cm` → 保存；
4. 打印机 →「打印首选项」→ 纸张尺寸选 `80x170` → 应用；
5. 「高级」里确认默认纸张同样是 `80x170`（**这一步最容易漏，漏了会按 A4 打、内容整体下移**）。

### 3. 启动

| 浏览器 | 脚本 |
|---|---|
| Chrome | `deploy/kiosk-print.cmd` |
| Chrome（无黑窗口） | `deploy/kiosk-print.vbs` |
| Edge | `deploy/kiosk-print-edge.cmd` |
| Edge（无黑窗口） | `deploy/kiosk-print-edge.vbs` |

双击即可，也可以传网址：`kiosk-print.cmd https://example.com/`。

开机自启：把 `.vbs` 的快捷方式放进 `shell:startup`（Win+R 输入 `shell:startup`）。

---

## 三、验证

1. 打一张手记，应**不弹任何对话框**直接出纸；
2. 服务端日志能看到本次打印：

   ```sh
   ssh ubuntu@119.29.168.14 'sudo journalctl -u amphion-gjh -n 50 | grep "journey print"'
   ```

   输出示例：

   ```
   journey print paper=80mm x 170mm css=80mm 170mm root=0x0 viewport=1280x799 dpr=2.0 elapsed_ms=826 session=ce342ade
   ```

   - `elapsed_ms` 在 1 秒左右 = 静默打印生效；
   - 几万毫秒 = 还在弹对话框等人操作。

3. 确认参数生效：临时去掉 `--kiosk` 启动，地址栏输入 `chrome://version`（Edge 是 `edge://version`），命令行里应包含 `--kiosk-printing`。

---

## 四、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 仍然弹打印对话框 | 浏览器没有完全退出，参数未生效 | 脚本里已 `taskkill` / `quit`，确认没有残留进程 |
| 打印到 A4、内容下移或被裁 | 打印机默认纸张不是 80×170 | 重做「设置默认纸张」那一步 |
| 内容边缘被切 | 打印机物理不可打印区 | 调整打印缩放：`journey.css` 里的 `--print-scale`（1 = 满幅，0.97 = 缩 3%） |
| 打出来是空白 | 纸张尺寸对不上，内容被裁到页外 | 先在打印预览里确认整页可见 |
| 静默打印对不齐 | 系统里还有别的队列 | 确认默认打印机就是 EPSON L3350 |

### macOS 驱动说明

如果 `lpoptions -p <打印机> -l` 报 `No such file or directory`，说明队列的 PPD 缺失。需要在 PPD 里补一个具名纸型：

```
*PageSize 80x170mm/80x170mm: "<</PageSize[226.7717 481.8898]/ImagingBBox null/Orientation 0>>setpagedevice"
*DefaultPageSize: 80x170mm
```

然后 `sudo launchctl kickstart -k system/org.cups.cupsd`，用 `lpoptions -p <打印机> -l | grep PageSize` 确认列表里出现 `*80x170mm`。

---

## 五、浏览器版本要求

页面用到的较新 API 与最低版本：

| 特性 | 最低版本 | 说明 |
|---|---|---|
| 容器查询（`cqw`） | Chrome/Edge 105 | 手记排版依赖 |
| `AbortSignal.timeout` | 103 | 已有兼容封装 |
| `AbortSignal.any` | 116 | 已用 `abortSignals.js` 兼容旧版 |

Windows 7/8.1 最高只能装 Edge/Chrome 109，因此 `AbortSignal.any` 必须走兼容实现（已处理）。更老的浏览器不建议使用。
