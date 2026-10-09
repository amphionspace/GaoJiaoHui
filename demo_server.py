#!/usr/bin/env python3
"""Amphion 三类语音接口本地 Web Demo 服务器。

用法：
  python3 demo_server.py            # 默认 http://localhost:8765
  PORT=9000 python3 demo_server.py

职责：
  1. 静态服务同目录 demo.html（浏览器打开 http://localhost:8765/）
  2. /proxy/* 反向代理到 https://amphion.top/*（网关未开 CORS，
     浏览器的 HTTP 请求经本代理同源转发；WS 由浏览器直连公网，不受 CORS 限制）
仅依赖 Python 3 标准库。
"""
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://amphion.top"
PORT = int(os.environ.get("PORT", "8765"))
ROOT = os.path.dirname(os.path.abspath(__file__))
HOP_HEADERS = {"host", "connection", "content-length", "transfer-encoding",
               "accept-encoding", "origin", "referer", "user-agent"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[demo] %s %s\n" % (self.address_string(), fmt % args))

    # ---- 静态 ----
    def _serve_static(self):
        path = "demo.html" if self.path in ("/", "/index.html") else None
        if not path:
            self.send_error(404, "Not Found")
            return
        try:
            with open(os.path.join(ROOT, path), "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404, "demo.html missing")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---- 代理 ----
    def _proxy(self, method):
        target = UPSTREAM + self.path[len("/proxy"):]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        req = urllib.request.Request(target, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                status, ctype, data = resp.status, resp.headers.get("Content-Type",
                                                                    "application/octet-stream"), resp.read()
        except urllib.error.HTTPError as e:
            status, ctype = e.code, e.headers.get("Content-Type", "application/json")
            data = e.read()
        except Exception as e:  # 网络错误等
            status, ctype, data = 502, "application/json", (
                '{"detail":"proxy error: %s"}' % str(e)[:200]).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        if self.path == "/" or self.path.startswith("/index") or self.path.startswith("/demo"):
            if method == "GET":
                return self._serve_static()
            self.send_error(405)
        elif self.path.startswith("/proxy/"):
            return self._proxy(method)
        else:
            self.send_error(404)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


def main():
    addr = ("127.0.0.1", PORT)
    print("Amphion Demo Server -> %s  (静态页 + /proxy -> %s)" % (addr, UPSTREAM))
    print("浏览器打开: http://localhost:%d/  （Ctrl+C 退出）" % PORT)
    ThreadingHTTPServer(addr, Handler).serve_forever()


if __name__ == "__main__":
    main()
