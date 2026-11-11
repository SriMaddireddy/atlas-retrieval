# Atlas completion evidence

AI-assisted verification by ChatGPT Work on 2026-11-11 UTC.

## Accepted scope

The deliverable is a single-process local synthetic incident knowledge service
with tenant-filtered retrieval, durable jobs, immutable snapshots and cited
extractive answers. Optional local generation retains its separately recorded
smoke evidence and known factuality limits. Internet-facing deployment and
indefinitely unattended storage operation remain future engineering work.

## Verification

- All 41 unit and HTTP integration tests passed in 2.203 seconds on Linux
  6.18.57, glibc 2.41, Python 3.12.14 and NumPy 2.3.5.
- Forty concurrent queue submissions across eight workers admitted exactly 32
  jobs. A running job continued to count against capacity. Marking it failed
  allowed a replacement. The HTTP overload path returned 429 without a job ID.
- An injected duplicate chunk caused publication rollback. Active documents,
  version, FTS results and running-job state survived together.
- Old versions remained searchable before cleanup. Cleanup removed stale
  chunks and FTS rows while preserving active versions for both tenants.
- Three successive rebuilds followed by an actual Service restart pruned stale
  chunks, retained version 4 and retrieved the committed document.
- A fresh source server and temporary database passed scripts/http_smoke.py,
  covering authentication, tenant filtering, cache hit, durable indexing,
  publication and extractive citations.
- The 36-query synthetic regression retained BM25 recall@5 1.0000 and MRR@5
  0.9583, LSA 0.9444 / 0.9097, and hybrid 0.9722 / 0.9375.
  All three unknown queries abstained.
- A fresh benchmark used 474 replicated synthetic documents, eight workers
  and 600 queries per path. Cache-disabled throughput was 645.73 queries/sec
  with p95 20.342 ms. Warm-cache throughput was 7163.71 queries/sec with
  p95 2.920 ms and 600 cache hits. Both paths returned zero empty results.
  Nine queued rebuilds took 1.132 seconds. These in-process measurements exclude
  HTTP and generation and do not establish production capacity.
- [Hosted CI run 43044626090](https://github.com/SriMaddireddy/atlas-retrieval/actions/runs/43044626090)
  passed on audit commit `8dd6e312d253fff29583b41e708e021cf22f04a9`, including
  pinned dependencies, all tests, container build and health check, live HTTP
  smoke, evaluation and benchmark.

Run the README verification commands to reproduce. CI uploads its JSON reports
and container log as the atlas-verification artifact. See the Actions run
associated with the audit commit for the pinned-environment outcome.

## Storage operating boundary

Old index versions are deliberately retained until restart so in-flight queries
can finish on the version they captured. Stop the server between demonstration
sessions and start it again against the same database to prune stale index
rows. For Compose, use docker compose down then docker compose up -d --wait.
The named volume retains documents and job records.

Completed jobs and their payloads are retained. Logical pruning does not shrink
SQLite's high-water file allocation or certify physical deletion. Monitor the
database and volume size. A throwaway synthetic demo can be reset with
docker compose down -v, which permanently deletes that demo's data.
Use backups and an explicit retention policy before adapting this to real data.
Automatic online garbage collection, job retention and compaction are deferred.

## Completion decision

Setup, API usage, architecture, tradeoffs, regression baselines and end-to-end
demo are documented and verified for the accepted scope. No critical defect
was identified in this audit. The audit commit passed CI, completing this scope. Continue with
`ad-impression-telemetry`.
Additional models, independent relevance datasets, strict per-tenant BM25
statistics, online storage collection and distributed deployment are future
work and do not extend this milestone.
