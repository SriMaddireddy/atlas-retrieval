"""Bounded stdlib HTTP API. One process owns the durable indexing queue."""

import os, json, re, time, threading, secrets, hmac, logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .service import Service

ROOT = Path(__file__).resolve().parent.parent


class Problem(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "Atlas/1.0"

    def log_message(self, format, *args):
        pass  # Do not record auth headers, queries, or document bodies.

    def send(self, status, value, kind="application/json"):
        data = json.dumps(value).encode() if kind == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def tenant(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        tenant = None
        for key, value in self.server.keys.items():
            if hmac.compare_digest(supplied.encode(), key.encode()):
                tenant = value
        if not tenant:
            raise Problem(401, "Supply a valid team API key as a Bearer token")
        with self.server.rate_lock:
            now = time.monotonic()
            balance, last = self.server.rates.get(tenant, (60, now))
            balance = min(60, balance + (now - last) * 30)
            if balance < 1:
                raise Problem(429, "Team request rate exceeded; retry shortly")
            self.server.rates[tenant] = (balance - 1, now)
        return tenant

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise Problem(400, "Chunked request bodies are not supported")
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise Problem(400, "Invalid Content-Length")
        if not 0 < n <= 262144:
            raise Problem(413, "JSON body must be between 1 and 262144 bytes")
        try:
            value = json.loads(self.rfile.read(n))
        except (ValueError, UnicodeError):
            raise Problem(400, "Invalid JSON")
        if not isinstance(value, dict):
            raise Problem(400, "Expected a JSON object")
        return value

    def query(self, b):
        q = b.get("query")
        if not isinstance(q, str) or not q.strip() or len(q) > 500:
            raise Problem(400, "query must be 1–500 characters")
        return q.strip()

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        try:
            path = urlsplit(self.path).path
            if method == "GET" and path == "/healthz":
                return self.send(
                    200,
                    {
                        "status": "ok",
                        "service": "atlas",
                        "mode": "read-only"
                        if self.server.service.readonly
                        else "local-persistent",
                    },
                )
            static = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "application/javascript"),
                "/style.css": ("style.css", "text/css"),
            }
            if method == "GET" and path in static:
                file, kind = static[path]
                return self.send(200, (ROOT / "static" / file).read_bytes(), kind)
            tenant = self.tenant()
            svc = self.server.service
            if method == "GET" and path == "/v1/stats":
                return self.send(200, svc.stats(tenant))
            if method == "GET" and path == "/v1/documents":
                return self.send(200, {"documents": svc.store.documents(tenant)})
            if method == "GET" and path.startswith("/v1/jobs/"):
                job = svc.store.job(tenant, path.rsplit("/", 1)[1])
                if not job:
                    raise Problem(404, "Job not found")
                return self.send(200, job)
            if method == "POST" and path in ("/v1/search", "/v1/answer"):
                b = self.body()
                q = self.query(b)
                if path.endswith("answer"):
                    provider = b.get("provider", "extractive")
                    if provider not in ("extractive", "ollama"):
                        raise Problem(400, "provider must be extractive or ollama")
                    mode = b.get("mode", "hybrid")
                    if mode not in ("lexical", "dense", "hybrid"):
                        raise Problem(400, "Invalid retrieval mode")
                    return self.send(200, svc.answer(tenant, q, provider, mode))
                k = b.get("k", 5)
                mode = b.get("mode", "hybrid")
                if (
                    type(k) != int
                    or not 1 <= k <= 20
                    or mode not in ("lexical", "dense", "hybrid")
                ):
                    raise Problem(
                        400, "k must be 1–20; mode must be lexical, dense, or hybrid"
                    )
                return self.send(200, svc.search(tenant, q, k, mode))
            if method == "POST" and path == "/v1/documents":
                docs = self.body().get("documents")
                if not isinstance(docs, list) or not 1 <= len(docs) <= 50:
                    raise Problem(400, "documents must be a list of 1–50 entries")
                clean = []
                ids = set()
                for d in docs:
                    if not isinstance(d, dict):
                        raise Problem(400, "Each document must be an object")
                    key = d.get("id")
                    title = d.get("title")
                    body = d.get("body")
                    source = d.get("source", "local://" + str(key))
                    if (
                        not isinstance(key, str)
                        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key)
                        or key in ids
                    ):
                        raise Problem(
                            400, "Unique document IDs must match [a-zA-Z0-9_-]{1,80}"
                        )
                    if (
                        not isinstance(title, str)
                        or not 1 <= len(title) <= 160
                        or not isinstance(body, str)
                        or not 10 <= len(body) <= 12000
                    ):
                        raise Problem(
                            400, "title must be 1–160 chars and body 10–12000 chars"
                        )
                    if (
                        not isinstance(source, str)
                        or len(source) > 500
                        or not source.startswith(("https://", "local://"))
                    ):
                        raise Problem(
                            400,
                            "source must be an https:// or local:// label; sources are never fetched",
                        )
                    ids.add(key)
                    clean.append(
                        {"id": key, "title": title, "body": body, "source": source}
                    )
                return self.send(202, {"job_id": svc.enqueue(tenant, "upsert", clean)})
            if method == "DELETE" and path.startswith("/v1/documents/"):
                key = path.rsplit("/", 1)[1]
                if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key):
                    raise Problem(400, "Invalid document ID")
                return self.send(202, {"job_id": svc.enqueue(tenant, "delete", [key])})
            raise Problem(404, "Endpoint not found")
        except Problem as e:
            self.send(e.status, {"error": e.message})
        except PermissionError as e:
            self.send(403, {"error": str(e)})
        except OverflowError as e:
            self.send(429, {"error": str(e)})
        except ValueError as e:
            self.send(422, {"error": str(e)})
        except RuntimeError as e:
            self.send(503, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Request failed")
            self.send(500, {"error": "Internal error"})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, keys):
        super().__init__(address, Handler)
        self.service = service
        self.keys = keys
        self.rates = {}
        self.rate_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(32)

    def get_request(self):
        conn, addr = super().get_request()
        conn.settimeout(15)
        return conn, addr

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.sendall(
                b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n"
            )
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8092")))
    p.add_argument("--db", default=os.getenv("ATLAS_DB", "data/atlas.db"))
    a = p.parse_args()
    raw = os.getenv("ATLAS_KEYS")
    keys = (
        json.loads(raw)
        if raw
        else {"atlas-demo-platform": "platform", "atlas-demo-payments": "payments"}
    )
    if (
        not isinstance(keys, dict)
        or not keys
        or any(
            not isinstance(k, str)
            or len(k) < 16
            or not isinstance(v, str)
            or not re.fullmatch(r"[a-z0-9_-]{1,40}", v)
            for k, v in keys.items()
        )
    ):
        raise SystemExit("ATLAS_KEYS must map keys (16+ chars) to tenant slugs")
    if (
        a.host not in ("127.0.0.1", "localhost", "::1")
        and not raw
        and os.getenv("ATLAS_READ_ONLY") != "1"
    ):
        raise SystemExit(
            "Provide ATLAS_KEYS before binding publicly, or explicitly use ATLAS_READ_ONLY=1 demo mode"
        )
    svc = Service(
        a.db,
        ROOT / "data_seed/corpus.json",
        os.getenv("ATLAS_READ_ONLY") == "1",
        os.getenv("OLLAMA_URL"),
        os.getenv("OLLAMA_MODEL"),
    )
    server = Server((a.host, a.port), svc, keys)
    print(
        f"Atlas ready at http://{a.host}:{a.port} — "
        + ("read-only" if svc.readonly else "persistent local mode"),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        svc.close()


if __name__ == "__main__":
    main()
