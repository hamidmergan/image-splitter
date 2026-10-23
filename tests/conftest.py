import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


class FakeServer:
    """OpenAI-compatible server that answers box and rotation questions with set texts."""

    def __init__(self):
        self.requests = []
        self.boxes = '{"items": []}'
        self.rotation = "0"
        self.fail = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                outer.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if outer.fail:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                prompt = body["messages"][0]["content"][0]["text"]
                text = outer.boxes if "Find every separate item" in prompt else outer.rotation
                payload = {
                    "id": "x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": text},
                        }
                    ],
                }
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import os

    for name in list(os.environ):
        if name.startswith("IMAGE_SPLITTER_") or name == "OPENAI_API_KEY":
            monkeypatch.delenv(name)


@pytest.fixture
def save(tmp_path):
    """Save an RGB array (or several, as PDF pages) and return the path."""
    from PIL import Image

    def _save(name, *pages):
        path = tmp_path / name
        images = [Image.fromarray(p) for p in pages]
        if path.suffix == ".pdf":
            images[0].save(path, save_all=True, append_images=images[1:], resolution=72)
        else:
            images[0].save(path)
        return path

    return _save
