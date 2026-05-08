"""
api_server.py
n8n(Docker)からWindows上のPythonスクリプトを実行するためのHTTPサーバー。
ポート8765で待ち受け、n8nのHTTP Requestノードから呼び出す。

起動方法:
  python api_server.py

停止: Ctrl+C
"""

import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[api_server] {self.address_string()} - {format % args}")

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})

        elif self.path == "/summary":
            result = subprocess.run(
                [PYTHON, os.path.join(BASE_DIR, "scripts", "extract_report_summary.py")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.send_json(200, {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })

        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/run":
            result = subprocess.run(
                [PYTHON, os.path.join(BASE_DIR, "main.py")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=BASE_DIR,
            )
            success = result.returncode == 0
            self.send_json(200 if success else 500, {
                "success": success,
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })

        else:
            self.send_json(404, {"error": "Not found"})


if __name__ == "__main__":
    port = 8765
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"[api_server] 起動中 → http://localhost:{port}")
    print("[api_server] 停止するには Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[api_server] 停止しました")
