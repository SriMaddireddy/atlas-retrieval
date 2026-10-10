"""Immutable TF-IDF/LSA index; exact cosine search and reciprocal rank fusion."""

import re, math, hashlib
from collections import Counter
from dataclasses import dataclass
import numpy as np

STOP = set(
    "a an the is are was were to of and or in for with on how what when why do does i we our be by can from at as it this that should".split()
)


def tokens(s):
    return [
        t for t in re.findall(r"[a-z0-9_]+", s.lower()) if t not in STOP and len(t) > 1
    ]


def chunk_document(doc):
    words = doc["body"].split()
    out = []
    for n, start in enumerate(range(0, len(words), 140)):
        body = " ".join(words[start : start + 180])
        identity = f"{doc['id']}:{n}"
        out.append(
            {
                "id": hashlib.sha256(identity.encode()).hexdigest()[:16],
                "document_id": doc["id"],
                "title": doc["title"],
                "body": body,
                "source": doc.get("source", "local://" + doc["id"]),
            }
        )
        if start + 180 >= len(words):
            break
    return out


@dataclass(frozen=True)
class Snapshot:
    tenant: str
    version: int
    chunks: tuple
    vocabulary: dict
    idf: np.ndarray
    components: np.ndarray
    vectors: np.ndarray
    dimensions: int

    @classmethod
    def build(cls, tenant, version, chunks):
        counts = [Counter(tokens(c["title"] + " " + c["body"])) for c in chunks]
        freq = Counter(t for c in counts for t in c)
        # Bounded vocabulary keeps this exact-search learning baseline small.
        vocab = {
            t: i for i, t in enumerate(sorted(freq, key=lambda t: (-freq[t], t))[:8000])
        }
        idf = np.array(
            [math.log((1 + len(chunks)) / (1 + freq[t])) + 1 for t in vocab],
            dtype=np.float64,
        )
        matrix = np.zeros((len(chunks), len(vocab)), dtype=np.float64)
        for row, c in enumerate(counts):
            for t, n in c.items():
                if t in vocab:
                    matrix[row, vocab[t]] = (1 + math.log(n)) * idf[vocab[t]]
        if not chunks or not vocab:
            components = np.zeros((0, len(vocab)))
            vectors = np.zeros((len(chunks), 0))
            dims = 0
        else:
            matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
            # Deterministic randomized range finder, then exact SVD of the small projection.
            dims = min(48, max(1, len(chunks) - 1), len(vocab))
            width = min(dims + 8, min(matrix.shape))
            rng = np.random.default_rng(17)
            q, _ = np.linalg.qr(matrix @ rng.standard_normal((len(vocab), width)))
            for _ in range(2):
                q, _ = np.linalg.qr(matrix @ (matrix.T @ q))
            _, _, vt = np.linalg.svd(q.T @ matrix, full_matrices=False)
            components = vt[:dims]
            vectors = matrix @ components.T
            vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
        for a in (idf, components, vectors):
            if not np.isfinite(a).all():
                raise ValueError(
                    "Non-finite index values; previous snapshot must remain active"
                )
            a.setflags(write=False)
        return cls(
            tenant, version, tuple(chunks), vocab, idf, components, vectors, dims
        )

    def dense(self, query, limit=30):
        if not self.dimensions:
            return []
        q = np.zeros(len(self.vocabulary))
        count = Counter(tokens(query))
        for t, n in count.items():
            if t in self.vocabulary:
                q[self.vocabulary[t]] = (1 + math.log(n)) * self.idf[self.vocabulary[t]]
        q = q @ self.components.T
        norm = np.linalg.norm(q)
        if norm < 1e-12:
            return []
        scores = self.vectors @ (q / norm)
        return [
            (self.chunks[i]["id"], float(scores[i]))
            for i in np.argsort(-scores, kind="stable")[:limit]
            if scores[i] > 0.05
        ]

    def bytes(self):
        return self.idf.nbytes + self.components.nbytes + self.vectors.nbytes


def fuse(lexical, dense, mode, limit):
    streams = (
        [lexical]
        if mode == "lexical"
        else [dense]
        if mode == "dense"
        else [lexical, dense]
    )
    scores = {}
    details = {}
    for stream in streams:
        for rank, (key, score) in enumerate(stream, 1):
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
    for rank, (key, score) in enumerate(lexical, 1):
        details.setdefault(key, {})["lexical"] = {"rank": rank, "score": score}
    for rank, (key, score) in enumerate(dense, 1):
        details.setdefault(key, {})["dense"] = {"rank": rank, "score": round(score, 6)}
    return [
        (key, round(score, 8), details.get(key, {}))
        for key, score in sorted(scores.items(), key=lambda p: (-p[1], p[0]))[:limit]
    ]
