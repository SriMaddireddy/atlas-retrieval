"""Durable job queue and versioned tenant-scoped FTS tables. No untrusted SQL."""

import sqlite3, json, time, uuid
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as c:
            c.executescript("""PRAGMA journal_mode=WAL;
   CREATE TABLE IF NOT EXISTS versions(tenant TEXT PRIMARY KEY,version INTEGER NOT NULL);
   CREATE TABLE IF NOT EXISTS documents(tenant TEXT,id TEXT,title TEXT,body TEXT,source TEXT,PRIMARY KEY(tenant,id));
   CREATE TABLE IF NOT EXISTS chunks(tenant TEXT,version INTEGER,id TEXT,document_id TEXT,title TEXT,body TEXT,source TEXT,PRIMARY KEY(tenant,version,id));
   CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(tenant UNINDEXED,version UNINDEXED,id UNINDEXED,title,body,tokenize='porter unicode61');
   CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,tenant TEXT,kind TEXT,payload TEXT,status TEXT,created REAL,finished REAL,error TEXT,version INTEGER);
   CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,created);
   """)
            c.execute("UPDATE jobs SET status='pending' WHERE status='running'")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def prune_old_versions(self):
        with self.connect() as c:
            c.execute(
                "DELETE FROM chunks WHERE NOT EXISTS (SELECT 1 FROM versions v WHERE v.tenant=chunks.tenant AND v.version=chunks.version)"
            )
            c.execute(
                "DELETE FROM chunks_fts WHERE NOT EXISTS (SELECT 1 FROM versions v WHERE v.tenant=chunks_fts.tenant AND v.version=chunks_fts.version)"
            )

    def tenants(self):
        with self.connect() as c:
            return [x[0] for x in c.execute("SELECT tenant FROM versions")]

    def documents(self, tenant):
        with self.connect() as c:
            return [
                dict(x)
                for x in c.execute(
                    "SELECT id,title,body,source FROM documents WHERE tenant=? ORDER BY id",
                    (tenant,),
                )
            ]

    def version_chunks(self, tenant):
        with self.connect() as c:
            v = c.execute(
                "SELECT version FROM versions WHERE tenant=?", (tenant,)
            ).fetchone()
            version = v[0] if v else 0
            return version, [
                dict(x)
                for x in c.execute(
                    "SELECT id,document_id,title,body,source FROM chunks WHERE tenant=? AND version=? ORDER BY document_id,id",
                    (tenant, version),
                )
            ]

    def enqueue(self, tenant, kind, payload):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if (
                c.execute(
                    "SELECT count(*) FROM jobs WHERE status IN ('pending','running')"
                ).fetchone()[0]
                >= 32
            ):
                raise OverflowError("Index queue is full; retry later")
            key = uuid.uuid4().hex
            c.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    tenant,
                    kind,
                    json.dumps(payload),
                    "pending",
                    time.time(),
                    None,
                    None,
                    None,
                ),
            )
            return key

    def claim(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM jobs WHERE status='pending' ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                c.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
            return dict(row) if row else None

    def job(self, tenant, key):
        with self.connect() as c:
            row = c.execute(
                "SELECT id,kind,status,created,finished,error,version FROM jobs WHERE tenant=? AND id=?",
                (tenant, key),
            ).fetchone()
            return dict(row) if row else None

    def fail(self, key):
        with self.connect() as c:
            c.execute(
                "UPDATE jobs SET status='failed',finished=?,error='Index build failed; previous version remains active' WHERE id=?",
                (time.time(), key),
            )

    def publish(self, tenant, version, documents, chunks, job=None):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM documents WHERE tenant=?", (tenant,))
            c.executemany(
                "INSERT INTO documents VALUES(?,?,?,?,?)",
                [
                    (tenant, d["id"], d["title"], d["body"], d["source"])
                    for d in documents
                ],
            )
            c.executemany(
                "INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        tenant,
                        version,
                        x["id"],
                        x["document_id"],
                        x["title"],
                        x["body"],
                        x["source"],
                    )
                    for x in chunks
                ],
            )
            c.executemany(
                "INSERT INTO chunks_fts VALUES(?,?,?,?,?)",
                [(tenant, version, x["id"], x["title"], x["body"]) for x in chunks],
            )
            c.execute(
                "INSERT INTO versions VALUES(?,?) ON CONFLICT(tenant) DO UPDATE SET version=excluded.version",
                (tenant, version),
            )
            # Previous versions are retained while in-flight readers may still use their snapshot.
            if job:
                c.execute(
                    "UPDATE jobs SET status='complete',finished=?,version=? WHERE id=?",
                    (time.time(), version, job),
                )

    def lexical(self, tenant, version, query, limit=30):
        from .retrieval import tokens

        terms = list(dict.fromkeys(tokens(query)))[:32]
        if not terms:
            return []
        match = " OR ".join('"' + t + '"' for t in terms)
        with self.connect() as c:
            return [
                (x["id"], -float(x["score"]))
                for x in c.execute(
                    "SELECT id,bm25(chunks_fts,0,0,0,2,1) AS score FROM chunks_fts WHERE chunks_fts MATCH ? AND tenant=? AND version=? ORDER BY score,id LIMIT ?",
                    (match, tenant, version, limit),
                )
            ]

    def stats(self, tenant):
        with self.connect() as c:
            return {
                "documents": c.execute(
                    "SELECT count(*) FROM documents WHERE tenant=?", (tenant,)
                ).fetchone()[0],
                "jobs": {
                    x[0]: x[1]
                    for x in c.execute(
                        "SELECT status,count(*) FROM jobs WHERE tenant=? GROUP BY status",
                        (tenant,),
                    )
                },
            }
