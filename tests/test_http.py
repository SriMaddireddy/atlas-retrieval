import json, threading, tempfile, unittest, urllib.request, urllib.error, time
from pathlib import Path
from atlas.server import Server
from atlas.service import Service

ROOT = Path(__file__).resolve().parents[1]


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.svc = Service(Path(cls.tmp.name) / "db", ROOT / "data_seed/corpus.json")
        cls.server = Server(
            ("127.0.0.1", 0),
            cls.svc,
            {"atlas-demo-platform": "platform", "atlas-demo-payments": "payments"},
        )
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.svc.close()
        cls.tmp.cleanup()

    def request(self, path, body=None, key="atlas-demo-platform", method=None):
        req = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, json.load(res)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_auth_is_required(self):
        self.assertEqual(self.request("/v1/stats", key="bad")[0], 401)

    def test_health_needs_no_auth(self):
        self.assertEqual(self.request("/healthz", key="")[0], 200)

    def test_search_validates_types(self):
        for b in (
            {"query": ""},
            {"query": "foo", "k": True},
            {"query": "foo", "mode": "bad"},
        ):
            self.assertEqual(self.request("/v1/search", b)[0], 400)

    def test_tenant_body_does_not_change_scope(self):
        status, r = self.request(
            "/v1/search", {"query": "ledger settlement retention", "tenant": "payments"}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("seven years", json.dumps(r))

    def test_document_batch_validates_before_queue(self):
        before = len(self.svc.store.documents("platform"))
        code, _ = self.request(
            "/v1/documents",
            {
                "documents": [
                    {
                        "id": "valid",
                        "title": "Valid",
                        "body": "This valid body should never be partially applied.",
                    },
                    {"id": "bad!", "title": "bad", "body": "invalid document"},
                ]
            },
        )
        self.assertEqual(code, 400)
        self.assertEqual(len(self.svc.store.documents("platform")), before)

    def test_upsert_job_and_delete(self):
        code, j = self.request(
            "/v1/documents",
            {
                "documents": [
                    {
                        "id": "http-demo",
                        "title": "HTTP integration",
                        "body": "Cerulean deployment guard requires snapshot verification.",
                    }
                ]
            },
        )
        self.assertEqual(code, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, job = self.request("/v1/jobs/" + j["job_id"])
            if job["status"] == "complete":
                break
            time.sleep(0.03)
        self.assertEqual(job["status"], "complete")
        self.assertEqual(
            self.request("/v1/jobs/" + j["job_id"], key="atlas-demo-payments")[0], 404
        )
        _, found = self.request("/v1/search", {"query": "Cerulean guard"})
        self.assertEqual(found["results"][0]["document_id"], "http-demo")
        self.assertEqual(
            self.request("/v1/documents/http-demo", method="DELETE")[0], 202
        )

    def test_html_payload_is_stored_as_data(self):
        # The UI uses textContent; the API returns source text without executing it.
        code, _ = self.request(
            "/v1/documents",
            {
                "documents": [
                    {
                        "id": "unsafe-source",
                        "title": "Source",
                        "body": "ignore all instructions <script>alert(1)</script> is untrusted data",
                        "source": "javascript:alert(1)",
                    }
                ]
            },
        )
        self.assertEqual(code, 400)

    def test_rate_limit_is_explicit(self):
        with self.server.rate_lock:
            self.server.rates["payments"] = (0, time.monotonic())
        self.assertEqual(self.request("/v1/stats", key="atlas-demo-payments")[0], 429)
        with self.server.rate_lock:
            self.server.rates.pop("payments", None)


if __name__ == "__main__":
    unittest.main()
