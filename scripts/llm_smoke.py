"""Explicit loopback-only smoke. Requires local Ollama; no cloud calls."""

import argparse, json, time, urllib.request, pathlib

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8092")
p.add_argument("--output", default="llm-smoke.json")
a = p.parse_args()
from urllib.parse import urlsplit

assert urlsplit(a.url).hostname in ("localhost", "127.0.0.1", "::1"), (
    "Only a loopback server is allowed"
)
questions = [
    "How can search continue while a new index is being built?",
    "Why use reciprocal rank fusion instead of adding BM25 and cosine scores?",
    "How do we avoid duplicate writes after a client timeout?",
]
rows = []
for query in questions:
    start = time.perf_counter()
    req = urllib.request.Request(
        a.url + "/v1/answer",
        data=json.dumps({"query": query, "provider": "ollama"}).encode(),
        headers={
            "Authorization": "Bearer atlas-demo-platform",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        result = json.load(response)
    assert (
        not result["abstained"]
        and result["citations"]
        and result["provider"] == "ollama"
    ), result
    rows.append(
        {
            "query": query,
            "seconds": round(time.perf_counter() - start, 3),
            "answer": result["answer"],
            "citations": result["citations"],
        }
    )
report = {
    "status": "PASS",
    "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "provider": "local Ollama / qwen2.5:1.5b",
    "cases": rows,
    "scope": "Three live local generation checks with valid retrieved citation IDs. This is not a factuality, safety, or prompt-injection robustness benchmark.",
}
pathlib.Path(a.output).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(a.output).write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
