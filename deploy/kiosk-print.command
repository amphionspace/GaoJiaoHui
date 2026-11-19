#!/bin/sh
# 电话亭静默打印启动器（macOS）
#
# 作用：用 --kiosk-printing 启动 Chrome，让页面里的 window.print()
# 直接送默认打印机，不再弹出打印对话框和预览。
#
# 使用前必须完成两件事，否则会打到别的纸或别的打印机：
#   1. 系统设置 → 打印机与扫描仪 → 把 EPSON L3350 设为“默认打印机”；
#   2. 在打印对话框里新建 80×170mm 自定纸张，选中后存成默认预设
#      （预设 → 存储当前设置作为预设，并设为默认）。
#
# 用法：
#   chmod +x kiosk-print.command
#   双击运行，或 ./kiosk-print.command [网址]
#
# 退出全屏：按 Control+Command+F，或 Command+Q 退出 Chrome。

set -e
URL="${1:-https://amphion-gjh.amphiondev.com/}"
PROFILE="$HOME/Library/Application Support/booth-chrome"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -x "$CHROME" ]; then
  echo "找不到 Chrome：$CHROME" >&2
  exit 1
fi

# 已经开着的 Chrome 不会接受新参数，必须先完全退出。
osascript -e 'quit app "Google Chrome"' 2>/dev/null || true
sleep 2
pkill -f "Google Chrome" 2>/dev/null || true

exec "$CHROME" \
  --kiosk \
  --kiosk-printing \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  "$URL"
