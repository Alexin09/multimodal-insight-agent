"""
Lightweight proxy server with SSE streaming support.
Uses raw socket forwarding for streaming endpoints.
"""

import http.server
import socket
import os
import sys
import json
from urllib.parse import urlparse
import threading
import io

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")
PORT = int(os.environ.get("PORT", "3210"))
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

_parsed = urlparse(BACKEND)
BACKEND_HOST = _parsed.hostname or "localhost"
BACKEND_PORT = _parsed.port or 8000


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/v1/") or self.path == "/health":
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/v1/"):
            self._proxy("POST")
        else:
            self.send_error(404)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _proxy(self, method):
        body = b""
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0))
            if length:
                body = self.rfile.read(length)

        # Build raw HTTP request
        req_lines = [f"{method} {self.path} HTTP/1.1"]
        req_lines.append(f"Host: {BACKEND_HOST}:{BACKEND_PORT}")
        for key in ("Content-Type", "Authorization", "Accept"):
            val = self.headers.get(key)
            if val:
                req_lines.append(f"{key}: {val}")
        if body:
            req_lines.append(f"Content-Length: {len(body)}")
        req_lines.append("Connection: keep-alive")
        req_lines.append("")
        req_lines.append("")
        raw_req = "\r\n".join(req_lines).encode() + body

        try:
            # Connect to backend
            sock = socket.create_connection((BACKEND_HOST, BACKEND_PORT), timeout=120)
            sock.sendall(raw_req)

            # Read response headers
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk

            header_end = buf.index(b"\r\n\r\n")
            header_bytes = buf[:header_end]
            body_start = buf[header_end + 4 :]

            # Parse status line and headers
            header_lines = header_bytes.decode("utf-8", errors="replace").split("\r\n")
            status_line = header_lines[0]  # e.g. "HTTP/1.1 200 OK"
            status_code = int(status_line.split(" ")[1])

            resp_headers = {}
            for line in header_lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    resp_headers[k.strip().lower()] = v.strip()

            content_type = resp_headers.get("content-type", "")
            is_stream = "text/event-stream" in content_type

            # Send response to client
            self.send_response(status_code)
            if content_type:
                self.send_header("Content-Type", content_type)
            self._cors()
            self.end_headers()

            # Forward body
            is_chunked = resp_headers.get("transfer-encoding", "").lower() == "chunked"

            if is_stream:
                # For SSE: dechunk if needed, then forward
                raw_buf = body_start
                sock.settimeout(90)

                def read_more():
                    nonlocal raw_buf
                    try:
                        d = sock.recv(8192)
                        if d:
                            raw_buf += d
                            return True
                        else:
                            sys.stderr.write("[PROXY] read_more: recv returned empty\n")
                    except socket.timeout:
                        sys.stderr.write("[PROXY] read_more: socket timeout\n")
                    except (ConnectionResetError, BrokenPipeError) as e:
                        sys.stderr.write(f"[PROXY] read_more: {e}\n")
                    except Exception as e:
                        sys.stderr.write(f"[PROXY] read_more unexpected: {e}\n")
                    return False

                try:
                    if is_chunked:
                        # Dechunk: read "size\r\n...data...\r\n" frames
                        while True:
                            # Find chunk size line
                            while b"\r\n" not in raw_buf:
                                if not read_more():
                                    raise StopIteration
                            idx = raw_buf.index(b"\r\n")
                            size_str = raw_buf[:idx].decode().strip()
                            raw_buf = raw_buf[idx + 2 :]
                            chunk_size = int(size_str, 16)
                            if chunk_size == 0:
                                break
                            # Read chunk_size bytes + trailing \r\n
                            while len(raw_buf) < chunk_size + 2:
                                if not read_more():
                                    raise StopIteration
                            payload = raw_buf[:chunk_size]
                            raw_buf = raw_buf[chunk_size + 2 :]
                            self.wfile.write(payload)
                            self.wfile.flush()
                    else:
                        # Not chunked, just forward raw
                        if raw_buf:
                            self.wfile.write(raw_buf)
                            self.wfile.flush()
                        while True:
                            data = sock.recv(4096)
                            if not data:
                                break
                            self.wfile.write(data)
                            self.wfile.flush()
                except (StopIteration, BrokenPipeError, ConnectionResetError):
                    pass
            else:
                # Non-streaming: read all
                chunks = [body_start]
                content_length = resp_headers.get("content-length")
                if content_length:
                    remaining = int(content_length) - len(body_start)
                    while remaining > 0:
                        data = sock.recv(min(remaining, 8192))
                        if not data:
                            break
                        chunks.append(data)
                        remaining -= len(data)
                else:
                    while True:
                        data = sock.recv(8192)
                        if not data:
                            break
                        chunks.append(data)
                full_body = b"".join(chunks)
                self.wfile.write(full_body)
                self.wfile.flush()

            sock.close()

        except Exception as e:
            try:
                self.send_response(502)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            except Exception:
                pass

    def log_message(self, format, *args):
        path = args[0] if args else ""
        if "/v1/" in str(path) or "/health" in str(path):
            sys.stderr.write(f"\033[36m[PROXY] {format % args}\033[0m\n")
        else:
            sys.stderr.write(f"[STATIC] {format % args}\n")


if __name__ == "__main__":
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"✓ MultiModal Insight Agent")
    print(f"  Static:  http://localhost:{PORT}")
    print(f"  Proxy:   /v1/* → {BACKEND}")
    print(f"  Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
