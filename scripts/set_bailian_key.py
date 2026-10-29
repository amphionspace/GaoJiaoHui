"""Update the local provider key without echoing it or putting it in shell history."""
import getpass
import json
import os
from pathlib import Path
import tempfile


def main():
    path = Path(__file__).resolve().parents[1] / '.env.bailian.json'
    if not path.exists():
        raise SystemExit('未找到现有服务配置，请先配置服务地址。')
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            raise ValueError()
    except (ValueError, OSError):
        raise SystemExit('配置文件无法读取；未修改任何内容。')
    key = getpass.getpass('粘贴新的百炼 API Key（输入不显示，回车保存）：').strip()
    if not key:
        raise SystemExit('输入为空，原密钥未修改。')
    config['api_key'] = key
    fd, temp = tempfile.mkstemp(prefix='.env.bailian-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(config, output, ensure_ascii=False, indent=2)
            output.write('\n')
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print('本机密钥已更新，文件权限为仅当前用户可读写。未显示密钥。')
    print('如启动服务时设置了 BAILIAN_API_KEY 环境变量，需要更新或移除该变量后重启服务。')


if __name__ == '__main__':
    main()
