import urllib.request, urllib.error, json, time, argparse, pathlib

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8092")
p.add_argument("--output", default="http-smoke.json")
a = p.parse_args()


def request(path, body=None, key="atlas-demo-platform", method=None):
    req = urllib.request.Request(
        a.url + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


assert request("/healthz")["status"] == "ok"
r = request("/v1/search", {"query": "Kafka consumer lag", "mode": "hybrid"})
assert r["results"][0]["document_id"] == "lag"
assert request("/v1/search", {"query": "Kafka consumer lag"})["cache_hit"]
assert "seven years" not in json.dumps(
    request(
        "/v1/search", {"query": "ledger settlement retention", "tenant": "payments"}
    )
)
assert "seven years" in json.dumps(
    request(
        "/v1/search", {"query": "ledger settlement retention"}, "atlas-demo-payments"
    )
)
job = request(
    "/v1/documents",
    {
        "documents": [
            {
                "id": "smoke-quasar",
                "title": "Quasar ingestion smoke",
                "body": "The chartreuse Quasar smoke token verifies an atomic snapshot publication.",
            }
        ]
    },
)
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    state = request("/v1/jobs/" + job["job_id"])
    if state["status"] in ("complete", "failed"):
        break
    time.sleep(0.1)
assert state["status"] == "complete", state
assert (
    request("/v1/search", {"query": "chartreuse Quasar smoke"})["results"][0][
        "document_id"
    ]
    == "smoke-quasar"
)
answer = request("/v1/answer", {"query": "chartreuse Quasar smoke"})
assert answer["citations"] and answer["provider"] == "extractive"
report = {
    "status": "PASS",
    "scope": "Live HTTP authentication, tenant scope, cache hit, durable indexing job, atomic publication, cited quoted answer",
    "version": state["version"],
}
pathlib.Path(a.output).write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
