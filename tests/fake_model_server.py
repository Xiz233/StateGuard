from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeModelServer:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def __enter__(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                owner.requests.append({"path": self.path, "headers": dict(self.headers),
                                       "json": json.loads(self.rfile.read(length))})
                status, body = owner.responses.pop(0)
                self.send_response(status); self.send_header("Content-Type", "application/json")
                self.end_headers(); self.wfile.write(body if isinstance(body, bytes)
                                                      else json.dumps(body).encode())
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        return self

    def __exit__(self, *args):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
