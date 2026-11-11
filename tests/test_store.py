import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from atlas.retrieval import chunk_document
from atlas.store import Store


class StoreBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "atlas.db")

    def tearDown(self):
        self.temp.cleanup()

    def document(self, body="Quartz recovery uses the violet token."):
        return dict(id="recovery", title="Recovery", body=body, source="local://recovery")

    def test_concurrent_queue_capacity_and_recovery(self):
        def enqueue(index):
            try:
                return self.store.enqueue("team", "delete", [str(index)])
            except OverflowError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(enqueue, range(40)))
        accepted = [key for key in results if key is not None]
        self.assertEqual(len(accepted), 32)
        self.assertEqual(len(set(accepted)), 32)
        claimed = self.store.claim()
        with self.assertRaises(OverflowError):
            self.store.enqueue("team", "delete", ["extra"])
        self.store.fail(claimed["id"])
        replacement = self.store.enqueue("team", "delete", ["replacement"])
        self.assertEqual(self.store.job("team", replacement)["status"], "pending")
        self.assertEqual(self.store.stats("team")["jobs"], dict(failed=1, pending=32))

    def test_prune_preserves_active_tenants_and_old_readers_until_cleanup(self):
        old = self.document()
        new = self.document("Quartz recovery uses the amber token.")
        self.store.publish("a", 1, [old], chunk_document(old))
        self.store.publish("b", 1, [old], chunk_document(old))
        self.store.publish("a", 2, [new], chunk_document(new))
        self.assertTrue(self.store.lexical("a", 1, "violet"))
        self.store.prune_old_versions()
        self.assertEqual(self.store.lexical("a", 1, "violet"), [])
        self.assertTrue(self.store.lexical("a", 2, "amber"))
        self.assertTrue(self.store.lexical("b", 1, "violet"))
        with self.store.connect() as connection:
            for table in ("chunks", "chunks_fts"):
                rows = connection.execute(
                    "SELECT tenant,version FROM " + table + " ORDER BY tenant"
                ).fetchall()
                self.assertEqual([tuple(row) for row in rows], [("a", 2), ("b", 1)])

    def test_failed_publication_rolls_back_documents_versions_and_job(self):
        old = self.document()
        new = self.document("Quartz recovery uses the amber token.")
        self.store.publish("team", 1, [old], chunk_document(old))
        key = self.store.enqueue("team", "upsert", [new])
        self.store.claim()
        chunks = chunk_document(new)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.publish("team", 2, [new], chunks + chunks, key)
        self.assertEqual(self.store.documents("team"), [old])
        self.assertEqual(self.store.version_chunks("team")[0], 1)
        self.assertEqual(self.store.job("team", key)["status"], "running")
        self.assertTrue(self.store.lexical("team", 1, "violet"))
        self.assertEqual(self.store.lexical("team", 2, "amber"), [])
