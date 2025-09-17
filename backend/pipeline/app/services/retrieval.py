# app/services/retrieval.py

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from haystack import Pipeline
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever
from haystack_integrations.components.embedders.voyage_embedders import VoyageTextEmbedder
from haystack.utils import Secret

try:
    from haystack_integrations.components.rankers.voyage import VoyageRanker
except ImportError:
    from haystack_integrations.components.rankers.voyage.ranker import VoyageRanker

from app.config import VOYAGE_EMBED_MODEL, RETRIEVAL_MIN_SCORE, VOYAGE_RERANK_MODEL
from app.utils import get_document_store

def build_retrieval_pipeline() -> Pipeline:
    store = get_document_store()
    embedder = VoyageTextEmbedder(model=VOYAGE_EMBED_MODEL, input_type="query")
    try:
        embedder.warm_up()
    except Exception:
        pass
    retriever = PgvectorEmbeddingRetriever(document_store=store, top_k=10)
    ranker = VoyageRanker(model=VOYAGE_RERANK_MODEL)

    pipe = Pipeline()
    pipe.add_component("embedder", embedder)
    pipe.add_component("retriever", retriever)
    pipe.add_component("ranker", ranker)
    pipe.connect("embedder.embedding", "retriever.query_embedding")
    pipe.connect("retriever.documents", "ranker.documents")
    return pipe

def run_retrieval(pipe: Pipeline, query: str, filters: Optional[Dict] = None) -> Tuple[List, List[Dict], List[Tuple[str, str]], List[str], str]:
    """
    Execute retrieval, apply reranker threshold, and return:
      (retrieved_docs, contexts, grouped_files, file_order, warning)
    """
    result = pipe.run({
        "embedder": {"text": query},
        "retriever": {"filters": filters or {}},
        "ranker": {"query": query, "top_k": 10},
    })

    ranked_docs = result.get("ranker", {}).get("documents") or []
    retrieved = ranked_docs or result.get("retriever", {}).get("documents", []) or []

    if ranked_docs:
        try:
            scores = [getattr(d, "score", None) for d in ranked_docs]
            top_score = next((s for s in scores if isinstance(s, (int, float))), 0.0)
            if top_score < RETRIEVAL_MIN_SCORE:
                ranked_docs = []
                retrieved = []
        except Exception:
            pass

    contexts: List[Dict] = []
    seen_files = set()
    for d in retrieved:
        meta = getattr(d, "meta", {}) or {}
        fname = meta.get("filename") or meta.get("path") or "document"
        if fname in seen_files:
            continue
        contexts.append({
            "id": getattr(d, "id", None),
            "filename": fname,
            "content": getattr(d, "content", "") or "",
            "start_line": meta.get("start_line"),
            "end_line": meta.get("end_line"),
        })
        seen_files.add(fname)

    warning = "" if retrieved else "Warning: no docs matched repo_id; answering without context.\n\n"

    grouped = defaultdict(list)
    file_order: List[str] = []
    for d in retrieved:
        meta = getattr(d, "meta", {}) or {}
        fname = meta.get("filename") or meta.get("path") or "document"
        if fname not in file_order:
            file_order.append(fname)
        s = int(meta.get("start_line") or 1)
        e = int(meta.get("end_line") or 1)
        grouped[fname].append((s, e, getattr(d, "content", "") or ""))

    grouped_files: List[Tuple[str, str]] = []
    for fname in file_order[:6]:
        spans = sorted(grouped[fname], key=lambda x: x[0])
        blocks = [f"(lines {s}–{e})\n{c}" for s, e, c in spans if (c or "").strip()]
        body = "\n\n---\n\n".join(blocks)
        if len(body) > 2500:
            body = body[:2500]
        grouped_files.append((fname, body))

    return retrieved, contexts, grouped_files, file_order, warning
