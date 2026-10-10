# Decisions and failure boundaries

## One query, one version

The worker reads active source documents, applies the queued mutation, chunks text into 180-word passages with 40-word overlap, and builds a new model away from the serving snapshot. A publication lock covers the SQLite transaction and the in-memory pointer swap. A query briefly takes this lock to capture a snapshot, then releases it before FTS or vector computation. Both retrieval branches use the captured version. Old FTS rows remain until process restart so a query that already captured an older snapshot can finish. On restart inactive versions are pruned before serving; old bytes may remain in SQLite free pages until a maintenance vacuum. Deletion means absence from the active index, not certified physical erasure.

The queue stores pending/running/complete/failed job state durably. A crash resets running jobs to pending at startup. Upserts replace whole documents by ID and deletes are idempotent. The publication transaction updates source documents, all new chunks, active version, and job completion together. The process lock prevents a second writer from resetting job state. This is explicitly one process per database. Old completed job records are retained; long-running installations need a job retention policy.

## Two retrieval baselines

FTS5 uses Porter tokenization and BM25. The vector branch uses log TF, smoothed IDF, row normalization, a deterministic randomized SVD (seed 17, two power iterations), and up to 48 dimensions. Training uses only index text; evaluation questions are not training input. Query vectors use the same vocabulary, IDF, and projection. Out-of-vocabulary queries can produce no dense evidence. The model is a corpus-trained statistical baseline; it has no pretrained knowledge or multilingual guarantees.

RRF adds `1/(60 + rank)` for each branch. Scores are ranking utilities, not probabilities or calibrated relevance confidence. Fusion can demote a good keyword match. On this project's small regression set BM25 performs better than hybrid; evaluate larger independent data before selecting production defaults. All three modes remain exposed for inspection. Dense retrieval scans every retained vector. There is no ANN/HNSW index or claim of million-document scalability.

FTS statistics are shared across tenant/version rows, although candidates and returned text are filtered by tenant/version. Another team's corpus can influence BM25 score statistics. Production strict statistical isolation should use separate per-tenant indexes. No cross-tenant document bodies are returned by the tested API.

## Resource and data controls

Credential lookup maps to a server-owned tenant. A body `tenant` field cannot change scope. Jobs, documents, query snapshots, cache keys, and metrics are tenant-scoped. Cache keys include tenant, version, normalized query, top-k, and mode. There are at most 256 cache entries, with a 30-second TTL. Publishing drops that tenant's entries. The cache is an optimization; concurrent misses may compute duplicate searches.

The API caps a body at 256 KiB, one batch at 50 documents, a document at 12,000 characters, a tenant at 500 active documents/1,500 chunks, a vocabulary at 8,000 terms, pending+running jobs at 32, and active HTTP handlers at 32. Per-tenant token buckets allow a burst of 60 and refill at 30 requests/second. These are process-local; replicas do not create a global budget. Dense arrays and SVD workspace consume memory outside the serialized vector-byte metric.

The stdlib HTTP server is a local lab endpoint. Internet-facing deployment would need an ingress/proxy with TLS, robust HTTP framing/slow-client defenses, secret rotation, access audits, and independent security review. No CORS access is enabled. The browser uses textContent for retrieved content and API keys are held in memory. Source labels are never fetched. Documents and queries stay on this machine during local inference; model-weight downloads use the official model registry.

## Generator failure handling

The default provider copies adjacent source sentences and labels the result as extractive. A lexical-overlap guard abstains on low evidence; this is a heuristic and can miss paraphrases or accept irrelevant overlap. The small local model receives the top evidence passage as JSON data, a system instruction, and a constrained claims/source-ID schema. Each generated claim selects its source ID from the retrieved set; the server renders the brackets and validates them again. Using one passage reduces irrelevant context for the small model but limits cross-document synthesis. Every returned bracketed citation must identify a retrieved passage. Unknown or missing IDs reject the answer. The implementation does not automatically retry or silently fall back after a failed model response. Local generation is limited to one simultaneous request and a timeout. Three transport/parse failures open a 30-second circuit. Citation failures reject the answer but do not count as transport failures.

A small model can still hallucinate, omit important information, or follow malicious document instructions. Citation validation proves only that the named source exists in the retrieved set. No factuality, entailment, or prompt-injection guarantee is claimed.

## Cloud engineering discussion without a cloud bill

The Docker image, readiness check, bounded API, durable queue, and versioned model lifecycle are implemented locally. No cloud resources were created. A future GCP design could use Cloud Run stateless query replicas, object storage for immutable index artifacts, Pub/Sub for work, a separate index builder, and a managed transactional metadata store. This requires a different shared storage model and global index-version coordination; copying SQLite onto independent ephemeral replicas does not solve persistence or tenant consistency. ANN retrieval, embedding-service batching, observability, and multi-region failover are future work, not features claimed here.
