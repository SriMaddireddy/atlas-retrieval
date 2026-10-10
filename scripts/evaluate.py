"""Offline labeled-query comparison. Does not call a language model or network."""

import sys, json, tempfile, argparse, time, platform
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas.service import Service

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--output", default="evaluation.json")
a = p.parse_args()
cases = json.loads((ROOT / "data_seed/evaluation.json").read_text())
report = {
    "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "platform": platform.platform(),
    "query_count": len(cases),
    "corpus": "24 original synthetic platform runbooks",
    "method": "Queries are excluded from index training. Corpus and labels were authored together; this is a regression set, not an independent benchmark.",
    "modes": {},
}
with tempfile.TemporaryDirectory() as d:
    svc = Service(Path(d) / "db", ROOT / "data_seed/corpus.json")
    try:
        for mode in ("lexical", "dense", "hybrid"):
            details = []
            for case in cases:
                result = svc.search(case["tenant"], case["query"], 5, mode, cache=False)
                ids = list(dict.fromkeys(x["document_id"] for x in result["results"]))
                relevant = set(case["relevant_document_ids"])
                rank = next((i for i, id in enumerate(ids, 1) if id in relevant), None)
                details.append(
                    {
                        "query": case["query"],
                        "expected": sorted(relevant),
                        "retrieved": ids,
                        "reciprocal_rank": 1 / rank if rank else 0,
                        "recall_at_5": len(set(ids) & relevant) / len(relevant),
                    }
                )
            report["modes"][mode] = {
                "mrr_at_5": round(
                    sum(x["reciprocal_rank"] for x in details) / len(details), 4
                ),
                "recall_at_5": round(
                    sum(x["recall_at_5"] for x in details) / len(details), 4
                ),
                "queries": details,
            }
        unknown = [
            "xylophone aardvark juggling",
            "photosynthesis chlorophyll stomata",
            "sourdough cinnamon baking",
        ]
        report["unanswerable_abstained"] = sum(
            svc.answer("platform", q)["abstained"] for q in unknown
        )
        report["unanswerable_queries"] = len(unknown)
    finally:
        svc.close()
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "modes"}))
print(
    json.dumps(
        {
            mode: {k: v for k, v in row.items() if k != "queries"}
            for mode, row in report["modes"].items()
        }
    )
)
assert report["modes"]["hybrid"]["recall_at_5"] >= 0.85, (
    "Regression: hybrid recall fell below .85"
)
assert report["unanswerable_abstained"] == len(unknown), (
    "Regression: unknown query did not abstain"
)
