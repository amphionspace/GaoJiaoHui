"""Start both local services and stop both on exit; never silently change ports."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    for port in (5173, 8767):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                raise SystemExit('Port %s is unavailable. Stop the existing local service before starting another.' % port)
    npm = shutil.which('npm')
    if not npm:
        raise SystemExit('Install Node.js (with npm) first.')
    children = []
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        children.append(subprocess.Popen([sys.executable, '-m', 'server.main'], cwd=ROOT,
            env={**os.environ, 'HOST': '127.0.0.1', 'PORT': '8767', 'JOURNEY_TTS_PROVIDER': 'bailian'}))
        children.append(subprocess.Popen([npm, 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
            cwd=ROOT / 'frontend', start_new_session=True,
            env={**os.environ, 'GAOJIAOHUI_BACKEND_URL': 'http://127.0.0.1:8767'}))
        print('Open http://127.0.0.1:5173/ ; Ctrl-C stops both services.', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for index, child in enumerate(children):
            if child.poll() is None:
                if index == 1:
                    os.killpg(child.pid, signal.SIGTERM)
                else:
                    child.terminate()
        for child in children:
            try:
                child.wait(timeout=45)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
