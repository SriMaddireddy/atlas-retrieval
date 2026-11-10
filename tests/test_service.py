import unittest, tempfile, time, json, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from atlas.service import Service
from atlas.retrieval import Snapshot, chunk_document

ROOT = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "db.sqlite"
        self.s = Service(self.path, ROOT / "data_seed/corpus.json")

    def tearDown(self):
        self.s.close()
        self.temp.cleanup()

    def wait(self, key, tenant="platform"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.s.store.job(tenant, key)
            if job["status"] in ("complete", "failed"):
                return job
            time.sleep(0.02)
        self.fail("Job timeout")

    def doc(
        self,
        id="novel",
        body="Quasar deployment requires the chartreuse recovery token for atomic rollback.",
    ):
        return {
            "id": id,
            "title": "Quasar recovery",
            "body": body,
            "source": "local://quasar",
        }

    def test_hybrid_has_rank_provenance(self):
        r = self.s.search("platform", "Kafka consumer lag")
        self.assertEqual(r["results"][0]["document_id"], "lag")
        self.assertIn("lexical", r["results"][0]["signals"])
        self.assertIn("dense", r["results"][0]["signals"])

    def test_tenants_have_separate_results_and_cache(self):
        a = self.s.search("platform", "ledger settlement retention")
        b = self.s.search("payments", "ledger settlement retention")
        self.assertNotIn("seven years", json.dumps(a))
        self.assertIn("seven years", json.dumps(b))
        self.assertFalse(b["cache_hit"])

    def test_cache_hit_and_version_invalidation(self):
        self.s.search("platform", "Quasar recovery")
        self.assertTrue(self.s.search("platform", "Quasar recovery")["cache_hit"])
        job = self.wait(self.s.enqueue("platform", "upsert", [self.doc()]))
        self.assertEqual(job["status"], "complete")
        result = self.s.search("platform", "Quasar recovery")
        self.assertFalse(result["cache_hit"])
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["results"][0]["document_id"], "novel")

    def test_delete_removes_all_retrievable_chunks(self):
        self.wait(self.s.enqueue("platform", "delete", ["lag"]))
        for mode in ("lexical", "dense", "hybrid"):
            self.assertNotIn(
                "lag",
                [
                    x["document_id"]
                    for x in self.s.search("platform", "Kafka consumer lag", 20, mode)[
                        "results"
                    ]
                ],
            )

    def test_cross_tenant_job_is_hidden(self):
        key = self.s.enqueue("platform", "upsert", [self.doc()])
        self.assertIsNone(self.s.store.job("payments", key))
        self.wait(key)

    def test_restart_recovers_committed_documents(self):
        self.wait(self.s.enqueue("platform", "upsert", [self.doc()]))
        self.s.close()
        self.s = Service(self.path)
        self.assertEqual(
            self.s.search("platform", "chartreuse recovery")["results"][0][
                "document_id"
            ],
            "novel",
        )
        self.assertEqual(self.s.stats("platform")["version"], 2)

    def test_failed_build_preserves_active_snapshot(self):
        with patch.object(Snapshot, "build", side_effect=RuntimeError("injected")):
            key = self.s.enqueue("platform", "upsert", [self.doc()])
            job = self.wait(key)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.s.stats("platform")["version"], 1)
        self.assertEqual(len(self.s.store.documents("platform")), 24)

    def test_atomic_snapshot_during_rebuild(self):
        original = Snapshot.build
        entered = threading.Event()
        resume = threading.Event()

        def delayed(*a, **kw):
            entered.set()
            resume.wait(3)
            return original(*a, **kw)

        with patch.object(Snapshot, "build", side_effect=delayed):
            key = self.s.enqueue("platform", "upsert", [self.doc()])
            self.assertTrue(entered.wait(2))
            for _ in range(5):
                self.assertEqual(self.s.search("platform", "Kafka lag")["version"], 1)
            resume.set()
            self.assertEqual(self.wait(key)["status"], "complete")
        self.assertEqual(self.s.search("platform", "Quasar")["version"], 2)

    def test_search_continues_while_job_admission_waits(self):
        entered = threading.Event()
        resume = threading.Event()
        original = self.s.store.enqueue

        def delayed_enqueue(*args):
            entered.set()
            if not resume.wait(5):
                raise TimeoutError("Test did not release queue admission")
            return original(*args)

        with patch.object(self.s.store, "enqueue", side_effect=delayed_enqueue):
            with ThreadPoolExecutor(max_workers=2) as pool:
                job = pool.submit(self.s.enqueue, "platform", "upsert", [self.doc()])
                try:
                    self.assertTrue(entered.wait(2))
                    search = pool.submit(self.s.search, "platform", "Kafka consumer lag")
                    result = search.result(timeout=2)
                    self.assertEqual(result["version"], 1)
                    self.assertEqual(result["results"][0]["document_id"], "lag")
                    self.assertFalse(job.done())
                finally:
                    resume.set()
                self.assertEqual(self.wait(job.result(timeout=2))["status"], "complete")

    def test_extractive_quotes_and_valid_citations(self):
        a = self.s.answer("platform", "database connection acquisition timeouts")
        self.assertEqual(a["provider"], "extractive")
        self.assertFalse(a["abstained"])
        self.assertTrue(a["citations"])
        evidence = " ".join(x["body"] for x in a["retrieval"]["results"])
        self.assertIn(a["answer"].split(" [")[0], evidence)

    def test_unknown_query_abstains(self):
        self.assertTrue(
            self.s.answer("platform", "xylophone aardvark juggling")["abstained"]
        )

    def test_unknown_citation_is_rejected(self):
        with patch.object(self.s, "_ollama", return_value="A claim [ffffffffffffffff]"):
            with self.assertRaises(ValueError):
                self.s.answer("platform", "Kafka consumer lag", "ollama")

    def test_generator_unconfigured_is_explicit(self):
        with self.assertRaisesRegex(RuntimeError, "Set OLLAMA"):
            self.s.answer("platform", "Kafka consumer lag", "ollama")

    def test_running_job_recovers_after_restart(self):
        self.s.stop.set()
        self.s.thread.join(5)
        key = self.s.store.enqueue("platform", "upsert", [self.doc()])
        self.assertEqual(self.s.store.claim()["id"], key)
        self.s.close()
        self.s = Service(self.path)
        self.assertEqual(self.wait(key)["status"], "complete")

    def test_worker_recovers_from_transient_claim_locks(self):
        import sqlite3

        for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED_SHAREDCACHE):
            with self.subTest(sqlite_errorcode=code):
                self.s.stop.set()
                self.s.thread.join(5)
                self.assertFalse(self.s.thread.is_alive())
                key = self.s.store.enqueue("platform", "upsert", [self.doc()])
                original = self.s.store.claim
                error = sqlite3.OperationalError("injected transient lock")
                error.sqlite_errorcode = code
                attempts = []

                def claim():
                    attempts.append(time.monotonic())
                    if len(attempts) == 1:
                        raise error
                    return original()

                self.s.stop.clear()
                self.s.thread = threading.Thread(target=self.s._worker, daemon=True)
                with patch.object(self.s.store, "claim", side_effect=claim):
                    with self.assertLogs(level="WARNING") as logs:
                        self.s.thread.start()
                        job = self.wait(key)
                    self.assertEqual(job["status"], "complete")
                    self.assertTrue(self.s.thread.is_alive())
                    self.assertGreaterEqual(len(attempts), 2)
                    self.assertIn("retrying job claim", logs.output[0])
                    self.assertEqual(
                        self.s.search("platform", "chartreuse recovery")["results"][0]["document_id"],
                        "novel",
                    )
                    self.s.stop.set()
                    self.s.thread.join(5)

    def test_claim_does_not_retry_non_lock_database_errors(self):
        import sqlite3

        self.s.stop.set()
        self.s.thread.join(5)
        self.s.stop.clear()
        error = sqlite3.OperationalError("injected missing table")
        error.sqlite_errorcode = sqlite3.SQLITE_ERROR
        try:
            with patch.object(self.s.store, "claim", side_effect=error) as claim:
                with self.assertRaisesRegex(sqlite3.OperationalError, "missing table"):
                    self.s._worker()
                self.assertEqual(claim.call_count, 1)
        finally:
            self.s.stop.set()

    def test_capacity_failure_preserves_version(self):
        docs = [self.doc(id="doc" + str(i)) for i in range(501)]
        key = self.s.enqueue("platform", "upsert", docs)
        self.assertEqual(self.wait(key)["status"], "failed")
        self.assertEqual(self.s.stats("platform")["version"], 1)

    def test_generator_rejects_non_loopback(self):
        self.s.ollama_url = "https://example.com"
        self.s.ollama_model = "qwen2.5:1.5b"
        with self.assertRaisesRegex(RuntimeError, "loopback"):
            self.s.answer("platform", "Kafka consumer lag", "ollama")

    def test_generator_backpressure(self):
        self.s.generation_slot.acquire()
        try:
            with self.assertRaises(OverflowError):
                self.s.answer("platform", "Kafka consumer lag", "ollama")
        finally:
            self.s.generation_slot.release()

    def test_generator_circuit_opens_after_transport_failures(self):
        import urllib.error

        self.s.ollama_url = "http://127.0.0.1:11435"
        self.s.ollama_model = "qwen2.5:1.5b"
        with patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("offline")
        ) as outgoing:
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    self.s.answer("platform", "Kafka consumer lag", "ollama")
            with self.assertRaisesRegex(RuntimeError, "circuit"):
                self.s.answer("platform", "Kafka consumer lag", "ollama")
            self.assertEqual(outgoing.call_count, 3)

    def test_process_lock_blocks_second_writer(self):
        with self.assertRaisesRegex(RuntimeError, "already owns"):
            Service(self.path)

    def test_close_timeout_retains_writer_lock_until_worker_exits(self):
        original = Snapshot.build
        entered = threading.Event()
        resume = threading.Event()

        def delayed(*args, **kwargs):
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("Test failed to release index build")
            return original(*args, **kwargs)

        with patch.object(Snapshot, "build", side_effect=delayed):
            key = self.s.enqueue("platform", "upsert", [self.doc()])
            try:
                self.assertTrue(entered.wait(2))
                # Simulate expiry of the join deadline without waiting 20 seconds.
                with patch.object(self.s.thread, "join", return_value=None):
                    with self.assertRaisesRegex(RuntimeError, "ownership retained"):
                        self.s.close()
                self.assertFalse(self.s.process_lock.closed)
                with self.assertRaisesRegex(RuntimeError, "already owns"):
                    Service(self.path)
            finally:
                resume.set()
                self.s.close()
        self.assertEqual(self.s.store.job("platform", key)["status"], "complete")
        restarted = Service(self.path)
        try:
            self.assertEqual(restarted.stats("platform")["version"], 2)
        finally:
            restarted.close()

    def test_empty_tenant_safe(self):
        self.assertEqual(self.s.search("empty", "query")["results"], [])

    def test_readonly_denies_mutation(self):
        self.s.readonly = True
        with self.assertRaises(PermissionError):
            self.s.enqueue("platform", "delete", ["lag"])

    def test_closed_service_rejects_jobs_without_persisting_them(self):
        self.s.close()
        before = self.s.store.stats("platform")["jobs"]
        with self.assertRaisesRegex(RuntimeError, "no job accepted"):
            self.s.enqueue("platform", "upsert", [self.doc()])
        self.assertEqual(self.s.store.stats("platform")["jobs"], before)

    def test_dead_worker_rejects_jobs_even_without_stop_signal(self):
        self.s.stop.set()
        self.s.thread.join(5)
        self.s.stop.clear()
        before = self.s.store.stats("platform")["jobs"]
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            self.s.enqueue("platform", "delete", ["lag"])
        self.assertEqual(self.s.store.stats("platform")["jobs"], before)

    def test_sql_metacharacters_are_data(self):
        self.assertIsInstance(
            self.s.search("platform", '" OR 1=1; DROP TABLE documents; --')["results"],
            list,
        )

    def test_chunking_stable_overlap(self):
        d = self.doc(body=" ".join("word" + str(i) for i in range(400)))
        a = chunk_document(d)
        self.assertEqual(len(a), 3)
        self.assertEqual(a, chunk_document(d))
        self.assertEqual(a[0]["body"].split()[-40:], a[1]["body"].split()[:40])


if __name__ == "__main__":
    unittest.main()
