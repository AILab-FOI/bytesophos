# app/services/indexing.py

"""
Indexing services for code repositories.

This module scans a repository for source files, chunks their contents, generates
embeddings with VoyageAI, and writes the results into:
  1) a pgvector-backed Haystack document store (ANN search), and
  2) relational tables: `documents` and `document_chunks`.

Progress is streamed via WebSocket broadcasts.

Environment Variables:
    EMBEDDINGS_INDEX (str): Name of the pgvector table to store embeddings.
        Defaults to "embeddings".
    VOYAGE_EMBED_MODEL (str): VoyageAI embedding model to use.
        Defaults to "voyage-code-2".

WebSocket Events:
    Emitted through :func:`app.services.ws._broadcast` with payloads like:
        Embedding phase:
            {"phase": "embedding", "event": "start|progress|complete|error",
             "processed": int, "total": int, "progress": int?}
        Indexing phase:
            {"phase": "indexing", "event": "start|progress|complete|file_indexed|error",
             "processed": int, "total": int, "progress": int?, "path": str?}
        Final completion:
            {"phase": "indexed", "progress": 100}
        Fatal error:
            {"phase": "error", "message": str}

Notes:
    - Hidden paths (any path segment beginning with ".") are skipped.
    - Chunks are created by :func:`app.chunking.chunk_code`.
    - Embeddings are produced by :class:`VoyageDocumentEmbedder`.
    - Vector ANN index: :class:`PgvectorDocumentStore` (Haystack).
    - Relational mirror: inserts into `documents` and `document_chunks`.
"""

import os
import hashlib
import logging
import asyncio
from threading import Thread, Event
from typing import List, Any, Optional, Set, Dict, Tuple
from uuid import UUID

from psycopg.types.json import Json

from haystack import Document
from haystack.utils import Secret
from haystack.document_stores.types import DuplicatePolicy
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.embedders.voyage_embedders import (
    VoyageDocumentEmbedder,
)

from app.services.file_utils import list_files
from app.services.ws import _broadcast
from app.chunking import chunk_code

from app.db import fetch_one, execute
from app.routes.repos import mark_repo_indexed
from app.config import (
    EMBEDDINGS_INDEX,
    VOYAGE_EMBED_MODEL
)

logger = logging.getLogger(__name__)

def _chunk_text(chunk: Any) -> str:
    """Normalize a chunk-like object to a text string."""
    if isinstance(chunk, str):
        return chunk.strip()
    if isinstance(chunk, dict):
        for key in ("content", "text", "code", "chunk", "body", "value"):
            val = chunk.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _is_hidden_path(rel_path: str) -> bool:
    """Whether any path segment starts with a dot ('.')."""
    parts = rel_path.replace("\\", "/").split("/")
    return any(p.startswith(".") for p in parts if p)


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _json_safe(obj: Any) -> Any:
    """Make objects JSON-serializable for Haystack meta payloads."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


async def _get_or_create_document(
    repo_id: str,
    rel_path: str,
    abs_path: str,
) -> str:
    """Return document_id for (repo_id, rel_path). Create if missing.

    We treat each file path under a repo as a single `documents` row.
    - title = rel_path
    - source_type = 'file'
    - source_uri = abs_path
    - metadata mirrors repo_id & filename
    """
    sel = await fetch_one(
        """
        SELECT id FROM documents
        WHERE repo_id = %(repo_id)s AND title = %(title)s
        LIMIT 1
        """,
        {"repo_id": repo_id, "title": rel_path},
    )
    if sel:
        await execute(
            "DELETE FROM document_chunks WHERE document_id = %(doc_id)s",
            {"doc_id": sel["id"]},
        )
        await execute(
            """
            UPDATE documents
            SET ingestion_status = 'indexing',
                ingested_at = NULL,
                metadata = metadata || %(meta)s::jsonb
            WHERE id = %(id)s
            """,
            {
                "id": sel["id"],
                "meta": Json({
                    "repo_id": repo_id,
                    "filename": rel_path,
                    "source_uri": abs_path,
                }),
            },
        )
        return str(sel["id"])

    ins = await fetch_one(
        """
        INSERT INTO documents (
            repo_id, title, description, source_type, source_uri,
            version, checksum, ingestion_status, metadata
        )
        VALUES (
            %(repo_id)s, %(title)s, NULL, 'file', %(source_uri)s,
            1, NULL, 'indexing',
            %(meta)s
        )
        RETURNING id
        """,
        {
            "repo_id": repo_id,
            "title": rel_path,
            "source_uri": abs_path,
            "meta": Json({
                "repo_id": repo_id,
                "filename": rel_path,
                "source_uri": abs_path,
            }),
        },
    )
    return str(ins["id"])


async def _insert_chunk_row(
    document_id: str,
    content: str,
    chunk_index: int,
    start_line: Optional[int],
    end_line: Optional[int],
    embedding: Optional[List[float]],
    embedding_model: Optional[str],
) -> None:
    """Insert one row into document_chunks (embedding may be None)."""
    await execute(
        """
        INSERT INTO document_chunks (
            document_id, chunk_text, chunk_hash, chunk_index,
            start_offset, end_offset, search_vector,
            embedding, embedding_model, embedding_created_at,
            embedding_metadata, token_count, metadata
        )
        VALUES (
            %(document_id)s, %(chunk_text)s, %(chunk_hash)s, %(chunk_index)s,
            NULL, NULL,
            to_tsvector('english', %(chunk_text)s),
            %(embedding)s, %(embedding_model)s, NOW(),
            %(embedding_metadata)s, NULL,
            %(metadata)s
        )
        """,
        {
            "document_id": document_id,
            "chunk_text": content,
            "chunk_hash": _sha1(f"{document_id}:{chunk_index}:{len(content)}"),
            "chunk_index": chunk_index,
            "embedding": embedding,                 
            "embedding_model": embedding_model,
            "embedding_metadata": Json({}),         
            "metadata": Json({                      
                "start_line": start_line,
                "end_line": end_line,
            }),
        },
    )


async def _finalize_document(doc_id: str) -> None:
    """Mark a single document as fully indexed."""
    await execute(
        """
        UPDATE documents
        SET ingestion_status = 'indexed', ingested_at = NOW()
        WHERE id = %(id)s
        """,
        {"id": doc_id},
    )


def index_repo(
    repo_path: str,
    repo_id: str,
    batch_size: int = 16,
    max_chars: int = 10_000,
    overlap: int = 200,
) -> None:
    """Index a repository into pgvector & relational tables.

    Args:
        repo_path: Absolute path to the repository on disk.
        repo_id: Repo identifier (matches your folder name under uploads/data).
        batch_size: Number of chunks per embedding batch.
        max_chars: Max characters per chunk.
        overlap: Overlap characters between adjacent chunks.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    all_chunks: List[Dict[str, Any]] = []
    for rel_path in list_files(repo_id):
        if _is_hidden_path(rel_path):
            continue

        abs_path = os.path.join(repo_path, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue

        for raw in chunk_code(rel_path, text, max_chars=max_chars, overlap=overlap):
            content = _chunk_text(raw)
            if not content:
                continue
            s_line = raw.get("start_line") if isinstance(raw, dict) else None
            e_line = raw.get("end_line") if isinstance(raw, dict) else None
            all_chunks.append(
                {
                    "filename": rel_path,
                    "abs_path": abs_path,
                    "content": content,
                    "start_line": s_line,
                    "end_line": e_line,
                }
            )

    total_chunks = len(all_chunks)

    if total_chunks == 0:
        _broadcast(repo_id, {
            "phase": "embedding",
            "event": "complete",
            "processed": 0,
            "total": 0,
            "progress": 100,
        })
        _broadcast(repo_id, {
            "phase": "indexing",
            "event": "complete",
            "processed": 0,
            "total": 0,
            "progress": 100,
        })
        _broadcast(repo_id, {"phase": "indexed", "progress": 100})
        try:
            asyncio.run_coroutine_threadsafe(mark_repo_indexed(repo_id), loop)
        except Exception:
            logger.exception("Failed to mark repo indexed for repo_id=%s", repo_id)
        return

    _broadcast(repo_id, {
        "phase": "embedding",
        "event": "start",
        "processed": 0,
        "total": total_chunks,
        "progress": 0,
    })
    _broadcast(repo_id, {
        "phase": "indexing",
        "event": "start",
        "processed": 0,
        "total": total_chunks,
        "progress": 0,
    })

    embedder = VoyageDocumentEmbedder(
        model=VOYAGE_EMBED_MODEL,
        input_type="document",
    )
    try:
        embedder.warm_up()
    except Exception:
        pass

    ready = Event()
    ready.set()

    store: Optional[PgvectorDocumentStore] = None

    sent_files: Set[str] = set()
    doc_id_cache: Dict[str, str] = {}
    finalized_docs: Set[str] = set()

    embed_done = 0
    index_done = 0
    last_emb_pct: Optional[int] = None
    last_idx_pct: Optional[int] = None

    def _ensure_document_id(rel_path: str, abs_path: str) -> str:
        """Sync call that schedules async _get_or_create_document and waits for result."""
        if rel_path in doc_id_cache:
            return doc_id_cache[rel_path]
        fut = asyncio.run_coroutine_threadsafe(
            _get_or_create_document(repo_id, rel_path, abs_path),
            loop,
        )
        doc_id = str(fut.result())
        doc_id_cache[rel_path] = doc_id
        return doc_id

    def _insert_chunk_sync(
        document_id: str,
        content: str,
        chunk_index: int,
        start_line: Optional[int],
        end_line: Optional[int],
        embedding: Optional[List[float]],
        embedding_model: Optional[str],
    ) -> None:
        fut = asyncio.run_coroutine_threadsafe(
            _insert_chunk_row(
                document_id=document_id,
                content=content,
                chunk_index=chunk_index,
                start_line=start_line,
                end_line=end_line,
                embedding=embedding,
                embedding_model=embedding_model,
            ),
            loop,
        )
        fut.result()

    def _finalize_document_sync(doc_id: str) -> None:
        if doc_id in finalized_docs:
            return
        fut = asyncio.run_coroutine_threadsafe(_finalize_document(doc_id), loop)
        fut.result()
        finalized_docs.add(doc_id)

    def _worker():
        """Background worker that performs embedding and indexing."""
        nonlocal store, embed_done, index_done, last_emb_pct, last_idx_pct

        try:
            for start in range(0, total_chunks, batch_size):
                batch = all_chunks[start: start + batch_size]

                docs: List[Document] = []
                mapping: List[Tuple[int, Dict[str, Any]]] = []

                for local_idx, item in enumerate(batch):
                    content = _chunk_text(item.get("content"))
                    if not content:
                        continue

                    rel_path = item["filename"]
                    abs_path = item["abs_path"]
                    s_line = item.get("start_line")
                    e_line = item.get("end_line")

                    doc_id = _ensure_document_id(rel_path, abs_path)

                    suffix = (
                        f"{s_line}-{e_line}"
                        if isinstance(s_line, int) and isinstance(e_line, int)
                        else f"{start + local_idx}"
                    )

                    meta = _json_safe({
                        "filename": rel_path,
                        "repo_id": repo_id,
                        "repoId": repo_id,
                        "start_line": s_line,
                        "end_line": e_line,
                        "document_id": str(doc_id),
                        "chunk_index": start + local_idx,
                    })

                    docs.append(
                        Document(
                            id=f"{repo_id}:{rel_path}:{suffix}",
                            content=content,
                            meta=meta,
                        )
                    )
                    mapping.append((start + local_idx, item))

                if not docs:
                    continue

                ready.wait()

                pipe_out = embedder.run(docs)
                embedded_docs: List[Document] = pipe_out["documents"]

                embed_done += len(embedded_docs)
                emb_pct = int(embed_done * 100 / max(1, total_chunks))
                if emb_pct != last_emb_pct:
                    last_emb_pct = emb_pct
                    _broadcast(repo_id, {
                        "phase": "embedding",
                        "event": "progress",
                        "processed": embed_done,
                        "total": total_chunks,
                        "progress": emb_pct,
                    })

                if store is None:
                    first_emb = next(
                        (d.embedding for d in embedded_docs if getattr(d, "embedding", None)),
                        None,
                    )
                    if first_emb is None:
                        raise RuntimeError("Failed to obtain embedding from first batch")
                    store = PgvectorDocumentStore(
                        connection_string=Secret.from_env_var("DATABASE_DSN"),
                        table_name=EMBEDDINGS_INDEX,
                        embedding_dimension=len(first_emb),
                        create_extension=True,
                        recreate_table=False,
                        search_strategy="hnsw",
                        hnsw_recreate_index_if_exists=False,
                        hnsw_index_creation_kwargs={"M": 16, "ef_construction": 200},
                        hnsw_index_name="haystack_hnsw_index",
                        hnsw_ef_search=50,
                    )

                store.write_documents(embedded_docs, policy=DuplicatePolicy.OVERWRITE)

                just_indexed_files: Set[str] = set()
                for d in embedded_docs:
                    meta = getattr(d, "meta", {}) or {}
                    rel = meta.get("filename")
                    doc_id = meta.get("document_id")
                    chunk_index = meta.get("chunk_index")

                    _insert_chunk_sync(
                        document_id=str(doc_id),
                        content=d.content or "",
                        chunk_index=int(chunk_index) if chunk_index is not None else 0,
                        start_line=meta.get("start_line"),
                        end_line=meta.get("end_line"),
                        embedding=getattr(d, "embedding", None),
                        embedding_model=VOYAGE_EMBED_MODEL,
                    )

                    if isinstance(rel, str):
                        just_indexed_files.add(rel)

                for rel in sorted(just_indexed_files):
                    if rel not in sent_files:
                        sent_files.add(rel)
                        _broadcast(repo_id, {
                            "phase": "indexing",
                            "event": "file_indexed",
                            "path": rel,
                        })

                index_done += len(embedded_docs)
                idx_pct = int(index_done * 100 / max(1, total_chunks))
                if idx_pct != last_idx_pct:
                    last_idx_pct = idx_pct
                    _broadcast(repo_id, {
                        "phase": "indexing",
                        "event": "progress",
                        "processed": index_done,
                        "total": total_chunks,
                        "progress": idx_pct,
                    })

                for rel in just_indexed_files:
                    doc_id = doc_id_cache.get(rel)
                    if doc_id:
                        _finalize_document_sync(doc_id)

            _broadcast(repo_id, {
                "phase": "embedding",
                "event": "complete",
                "processed": total_chunks,
                "total": total_chunks,
                "progress": 100,
            })
            _broadcast(repo_id, {
                "phase": "indexing",
                "event": "complete",
                "processed": total_chunks,
                "total": total_chunks,
                "progress": 100,
            })
            _broadcast(repo_id, {"phase": "indexed", "progress": 100})

            try:
                asyncio.run_coroutine_threadsafe(mark_repo_indexed(repo_id), loop)
            except Exception:
                logger.exception("Failed to mark repo indexed for repo_id=%s", repo_id)

        except Exception as e:
            logger.exception("Indexing failed for repo_id=%s", repo_id)
            _broadcast(repo_id, {"phase": "embedding", "event": "error", "error": str(e)})
            _broadcast(repo_id, {"phase": "indexing", "event": "error", "error": str(e)})
            _broadcast(repo_id, {"phase": "error", "message": str(e)})

    Thread(target=_worker, daemon=True, name=f"indexer-{repo_id[:6]}").start()
