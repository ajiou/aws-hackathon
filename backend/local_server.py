"""本機開發伺服器。SPEC §15.2。

用同一個 app.handler，資料從本機目錄讀，不需要 AWS 憑證。

    SERVING_DIR=../out/serving python backend/local_server.py
    SERVING_DIR=../frontend/mock python backend/local_server.py   # 先用 mock

前端接： VITE_API_BASE=http://localhost:8000/api/v1
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

PORT = int(os.environ.get("PORT", 8000))

# mock 目錄的檔名與 serving 不同，這裡做一層對照
MOCK_ALIAS = {"scores": "risk-top", "briefs": None}


def _patched_load(key):
    if app.SERVING_DIR and not os.path.exists(os.path.join(app.SERVING_DIR, f"{key}.json")):
        alias = MOCK_ALIAS.get(key, key)
        if alias is None:
            return {}
        if key == "scores":
            data = app._load(alias)
            return {"items": data["items"]}
    return _orig_load(key)


_orig_load = app._load
app._load = _patched_load


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):                                    # noqa: N802
        u = urlparse(self.path)
        qs = {k: ",".join(v) for k, v in parse_qs(u.query).items()}
        res = app.handler({"rawPath": u.path, "queryStringParameters": qs})
        body = res["body"].encode("utf-8")
        self.send_response(res["statusCode"])
        for k, v in res["headers"].items():
            self.send_header(k, v)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):                   # noqa: A003
        sys.stderr.write("  %s\n" % (fmt % args))


if __name__ == "__main__":
    if not app.SERVING_DIR:
        sys.exit("請設定 SERVING_DIR，例如 SERVING_DIR=../frontend/mock")
    print(f"serving dir : {os.path.abspath(app.SERVING_DIR)}")
    print(f"listening   : http://localhost:{PORT}/api/v1/meta")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
