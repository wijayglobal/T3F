"""Hybrid search: lexical match on English/Tamil text plus vector similarity.

Vectors come from a multilingual sentence model (fastembed, ONNX, CPU) so a
Tamil, Tanglish-free English or mixed query lands near related English terms.
If embeddings have not been built (`manage.py build_embeddings`) search quietly
falls back to lexical only.
"""
import re
import threading
import time

import numpy as np
from django.db.models import Q

from .models import Relation, Status, Suggestion, Term

PUBLIC = [Status.APPROVED, Status.DRAFT]

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384

_lock = threading.Lock()
_index_lock = threading.Lock()
_model = None
_index = {"ids": None, "mat": None, "count": -1, "checked": 0.0}
# Counting embedded terms scans every row (~0.3-0.5 s on 200k terms), so a worker only checks
# for a rebuilt index this often instead of on every search.
INDEX_RECHECK_SECONDS = 300

TAMIL = re.compile(r"[஀-௿]")


def get_model():
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding

            _model = TextEmbedding(model_name=MODEL_NAME)
        return _model


def embed(texts):
    # Bare single words collapse to near-identical vectors in this model
    # ("sad" ~ "now" ~ "gist"); a short wrapper restores meaningful geometry.
    wrapped = [f'the word "{t}"' for t in texts]
    vecs = np.array(list(get_model().embed(wrapped)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return vecs


def _load_index():
    with _index_lock:
        now = time.monotonic()
        stale = now - _index["checked"] >= INDEX_RECHECK_SECONDS
        if _index["count"] < 0 or (stale and Term.objects.exclude(embedding=None).count() != _index["count"]):
            rows = Term.objects.exclude(embedding=None).values_list("id", "embedding").iterator(chunk_size=20000)
            ids, blobs, n = [], [], 0
            for tid, blob in rows:
                n += 1
                if len(blob) == DIM * 4:
                    ids.append(tid)
                    blobs.append(bytes(blob))
            _index["ids"] = np.array(ids)
            _index["mat"] = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(-1, DIM)
            _index["count"] = n  # rows in the DB, so a malformed blob doesn't force reloads
        if stale or _index["checked"] == 0:
            _index["checked"] = now
        return _index if len(_index["ids"]) else None


def semantic_terms(query, limit=12, min_score=0.7):
    idx = _load_index()
    if idx is None:
        return []
    qv = embed([query])[0]
    sims = idx["mat"] @ qv
    limit = min(limit, len(sims))
    top = np.argpartition(-sims, limit - 1)[:limit]
    top = top[np.argsort(-sims[top])]
    return [(int(idx["ids"][i]), float(sims[i])) for i in top if sims[i] >= min_score]


def search(query, limit=30):
    """Return (terms, related_terms, relations) for a query string."""
    q = query.strip()
    if not q:
        return [], [], {}

    scores = {}

    def bump(tid, s):
        scores[tid] = max(scores.get(tid, 0), s)

    if TAMIL.search(q):
        for tid, tamil in Suggestion.objects.filter(
            hidden=False, status__in=PUBLIC, tamil__icontains=q
        ).values_list("term_id", "tamil")[:400]:
            bump(tid, 1.0 if tamil == q else 0.8 if tamil.startswith(q) else 0.6)
    else:
        ql = q.lower()
        for t in Term.objects.filter(text__icontains=ql).values_list("id", "text")[:400]:
            tid, text = t
            if text.lower() == ql:
                bump(tid, 1.0)
            elif text.lower().startswith(ql):
                bump(tid, 0.85)
            elif re.search(rf"\b{re.escape(ql)}", text.lower()):
                bump(tid, 0.7)
            else:
                bump(tid, 0.5)
        # roman (Tanglish) match on suggestions
        for tid in Suggestion.objects.filter(hidden=False, status__in=PUBLIC, roman__iexact=ql).values_list(
            "term_id", flat=True
        )[:50]:
            bump(tid, 0.9)

    # The model aligns Tamil poorly with English headwords, so Tamil queries stay literal.
    sem = {} if TAMIL.search(q) else dict(semantic_terms(q))
    lexical_ids = set(scores)
    for tid, s in sem.items():
        if tid not in lexical_ids:
            scores[tid] = s * 0.6  # keep related-by-meaning below literal matches

    ranked = sorted(scores, key=lambda t: -scores[t])[:limit]
    terms = {
        t.id: t
        for t in Term.objects.filter(id__in=ranked).defer("embedding").prefetch_related("suggestions")
    }
    ordered = [terms[i] for i in ranked if i in terms]
    direct = [t for t in ordered if t.id in lexical_ids]
    related = [t for t in ordered if t.id not in lexical_ids]
    return direct, related, relations_for(direct + related)


def relations_for(terms):
    words = {s.tamil for t in terms for s in t.suggestions.all() if s.is_public}
    out = {}
    if not words:
        return out
    for r in Relation.objects.filter(Q(word__in=words)):
        out.setdefault(r.word, {"syn": [], "ant": []})[r.kind].append(r.other)
    return out
