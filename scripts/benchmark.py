"""Synthetic in-process retrieval benchmark. No hosted APIs; excludes LLM latency."""

import sys, json, tempfile, time, platform, argparse, concurrent.futures
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas.service import Service

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--output", default="benchmark.json")
p.add_argument("--queries", type=int, default=600)
a = p.parse_args()
queries = [
    x["query"] for x in json.loads((ROOT / "data_seed/evaluation.json").read_text())
]
source = json.loads((ROOT / "data_seed/corpus.json").read_text())["platform"]


def percentile(values, p):
    return round(sorted(values)[min(len(values) - 1, int((len(values) - 1) * p))], 3)


def run(svc, cache, workers):
    def task(i):
        start = time.perf_counter()
        r = svc.search("platform", queries[i % len(queries)], 5, "hybrid", cache)
        return (time.perf_counter() - start) * 1000, len(r["results"]), r["cache_hit"]

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(task, range(a.queries)))
    duration = time.perf_counter() - start
    values = [x[0] for x in rows]
    return {
        "queries": len(rows),
        "workers": workers,
        "cache_enabled": cache,
        "seconds": round(duration, 4),
        "queries_per_second": round(len(rows) / duration, 2),
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "empty_results": sum(x[1] == 0 for x in rows),
        "cache_hits": sum(x[2] for x in rows),
    }


with tempfile.TemporaryDirectory() as d:
    svc = Service(Path(d) / "db", ROOT / "data_seed/corpus.json")
    try:
        # Replica text creates a larger load corpus, not a new relevance benchmark.
        docs = []
        for i in range(450):
            original = source[i % len(source)]
            docs.append(
                {
                    "id": "replica-" + str(i),
                    "title": original["title"] + " / service " + str(i),
                    "body": (original["body"] + " ") * 3,
                    "source": "local://synthetic-load/" + str(i),
                }
            )
        start = time.perf_counter()
        for startrow in range(0, len(docs), 50):
            svc.enqueue("platform", "upsert", docs[startrow : startrow + 50])
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            stats = svc.stats("platform")
            if stats["jobs"].get("pending", 0) + stats["jobs"].get("running", 0) == 0:
                break
            time.sleep(0.05)
        assert stats["documents"] == 474 and not stats["jobs"].get("failed", 0), stats
        build = time.perf_counter() - start
        uncached = run(svc, False, 8)
        for q in queries:
            svc.search("platform", q)
        cached = run(svc, True, 8)
        report = {
            "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform": platform.platform(),
            "index": svc.stats("platform"),
            "queued_rebuild_seconds": round(build, 3),
            "uncached": uncached,
            "warm_cache": cached,
            "scope": "In-process exact hybrid retrieval; excludes HTTP, authentication, rate limits, and local LLM generation. Synthetic replicated runbooks; not production traffic. Warm-cache results are explicitly separate.",
        }
    finally:
        svc.close()
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
