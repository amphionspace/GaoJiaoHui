"""Poll the local health endpoint and push state changes to a WeCom robot.

Run by journey-monitor.timer every minute. Only aggregate status is read: the
monitor never sees or stores a transcript, audio, key or admin credential. The
webhook URL itself is never logged.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = 'http://127.0.0.1:8766/api/health'
DEFAULT_STATE = '/var/lib/amphion-gjh/monitor.json'
REMIND_SECONDS = 600

CHECK_LABELS = {
    'service': '服务可达性',
    'frontend': '前端构建',
    'text': '文本模型',
    'asr': '语音识别',
    'tts': '声音合成',
    'disk': '磁盘',
}


def load_health(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def check_detail(name, check):
    if name == 'disk':
        return '磁盘 ' + str(check.get('percent')) + '%（剩余 ' + str(check.get('free_gb')) + 'G）'
    if name == 'text':
        return '文本模型 ' + (check.get('model') or '未配置')
    if name == 'tts':
        return '声音合成 ' + (check.get('provider') or '未配置')
    if name == 'asr':
        return '托管凭证' if check.get('managed') else '网关密钥'
    if name == 'frontend':
        return '已构建' if check.get('built') else '未构建'
    return name


def checks_from(health):
    checks = []
    status = health.get('status')
    specific = health.get('checks') or {}
    for name, check in specific.items():
        checks.append((name, bool(check.get('ok')), check_detail(name, check)))
    if status != 'ok' and all(ok for _, ok, _ in checks):
        checks.append(('service', False, '健康状态 ' + str(status)))
    return checks


def load_state(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def decide(state, checks, now):
    """Return (kind, key, detail) notifications and update the active flags."""
    previous = state.setdefault('checks', {})
    notifications = []
    for key, ok, detail in checks:
        entry = previous.setdefault(key, {'active': False, 'sent': 0})
        if not ok:
            if not entry.get('active') or now - entry.get('sent', 0) >= REMIND_SECONDS:
                notifications.append(('alert', key, detail))
            entry['active'] = True
        elif entry.get('active'):
            notifications.append(('recover', key, detail))
            entry['active'] = False
    return notifications


def build_message(kind, key, detail, public_url=''):
    label = CHECK_LABELS.get(key, key)
    if kind == 'alert':
        lines = ['**⚠️ 和 2036 对话 · 服务异常**', '> 检查：' + label, '> 详情：' + detail]
    else:
        lines = ['**✅ 和 2036 对话 · 已恢复**', '> 检查：' + label, '> 详情：' + detail]
    lines.append('> 时间：' + time.strftime('%Y-%m-%d %H:%M:%S'))
    if public_url:
        lines.append('> 地址：' + public_url)
    return '\n'.join(lines)


def send_webhook(webhook, text, timeout=5):
    payload = json.dumps({'msgtype': 'markdown', 'markdown': {'content': text}}, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(webhook, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2048)
        data = json.loads(body) if body else {}
        if isinstance(data, dict) and data.get('errcode') not in (None, 0):
            print('wecom rejected the alert: errcode', data.get('errcode'))
            return False
        return True
    except (OSError, ValueError) as error:
        print('wecom alert failed:', type(error).__name__)
        return False


def load_health_retry(url, attempts=2, delay=2.0):
    """A deploy restarts the app; one retry avoids paging on a one-second gap."""
    last = None
    for attempt in range(attempts):
        try:
            return load_health(url)
        except Exception as error:  # noqa: BLE001 - any transport failure is retried
            last = error
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise last


def run(url, state_path, webhook, public_url='', dry_run=False):
    try:
        checks = checks_from(load_health_retry(url))
    except Exception:
        checks = [('service', False, '健康接口不可达')]
    if dry_run:
        for key, ok, detail in checks:
            print(('OK   ' if ok else 'FAIL ') + key + ': ' + detail)
        return 0
    if not webhook:
        summary = '; '.join(key + ('=ok' if ok else '=fail') for key, ok, detail in checks)
        print('alert webhook not configured; ' + summary)
        return 0
    state = load_state(state_path)
    now = time.time()
    for kind, key, detail in decide(state, checks, now):
        if send_webhook(webhook, build_message(kind, key, detail, public_url)):
            state['checks'][key]['sent'] = now
            print('sent', kind, key)
    save_state(state_path, state)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    return run(
        os.environ.get('JOURNEY_MONITOR_URL', DEFAULT_URL).strip() or DEFAULT_URL,
        os.environ.get('JOURNEY_MONITOR_STATE', DEFAULT_STATE).strip() or DEFAULT_STATE,
        os.environ.get('JOURNEY_ALERT_WEBHOOK', '').strip(),
        os.environ.get('JOURNEY_PUBLIC_URL', '').strip(),
        '--dry-run' in argv,
    )


if __name__ == '__main__':
    sys.exit(main())
