"""Text embeddings for retrieval and matching.

Primary: BGE-M3 (multilingual, strong on German) via sentence-transformers – runs locally, no API cost.
Fallback: TF-IDF on character n-grams (no download needed), so everything still works offline.

    pip install sentence-transformers      # first use downloads BAAI/bge-m3 (~2 GB)
    export NR_EMBED=bge-m3                 # opt in; default is the TF-IDF fallback
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np


class _Tfidf:
    name = "tfidf-char"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True, sublinear_tf=True)
        self.fitted = False

    def encode(self, texts: list[str]) -> np.ndarray:
        if not self.fitted:
            self.vec.fit(texts)
            self.fitted = True
        m = self.vec.transform(texts).toarray().astype(np.float32)
        n = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.maximum(n, 1e-9)

    def fit(self, corpus: list[str]):
        self.vec.fit(corpus)
        self.fitted = True


class _BGE:
    name = "bge-m3"

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer("BAAI/bge-m3")

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True, batch_size=32), dtype=np.float32)

    def fit(self, corpus):
        pass


@lru_cache(maxsize=1)
def get_embedder():
    if os.environ.get("NR_EMBED", "").lower() in ("bge-m3", "bge", "bge_m3"):
        try:
            return _BGE()
        except Exception as e:  # missing package or no network: degrade gracefully
            print(f"[embeddings] BGE-M3 unavailable ({e.__class__.__name__}), using TF-IDF fallback")
    return _Tfidf()


def top_k(queries: list[str], corpus: list[str], k: int = 3) -> list[list[tuple[int, float]]]:
    """For each query, the k most similar corpus entries as (index, cosine)."""
    if not queries or not corpus:
        return [[] for _ in queries]
    emb = get_embedder()
    if isinstance(emb, _Tfidf):
        emb = _Tfidf()           # fit on this exact vocabulary
        emb.fit(corpus + queries)
    c = emb.encode(corpus)
    q = emb.encode(queries)
    sims = q @ c.T
    out = []
    for row in sims:
        idx = np.argsort(-row)[:k]
        out.append([(int(i), float(row[i])) for i in idx])
    return out
