# app/services/chunks.py

import hashlib
from typing import Dict, Optional, List
import re as _re

from app.db import fetch_one

def rewrite_doc_numbers_to_filenames(answer: str, file_order: List[str]) -> str:
    """Turn 'Document N' into `filename`."""
    def repl(m):
        idx = int(m.group(1)) - 1
        return f"`{file_order[idx]}`" if 0 <= idx < len(file_order) else m.group(0)
    return _re.sub(r'\bDocument\s+(\d+)\b', repl, answer)

async def resolve_chunk_id(meta: Dict, content: str) -> Optional[str]:
    """Map retriever meta/content to document_chunks.id for persistence."""
    chunk_id = meta.get("document_chunk_id") or meta.get("chunk_id")
    if chunk_id:
        row = await fetch_one(
            "SELECT id FROM document_chunks WHERE id = %(id)s LIMIT 1",
            {"id": chunk_id},
        )
        if row:
            return str(row["id"])

    doc_id = meta.get("document_id") or meta.get("doc_id")
    chunk_index = meta.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        row = await fetch_one(
            """
            SELECT id
            FROM document_chunks
            WHERE document_id = %(doc_id)s AND chunk_index = %(idx)s
            LIMIT 1
            """,
            {"doc_id": doc_id, "idx": chunk_index},
        )
        if row:
            return str(row["id"])

    text = (content or "").strip()
    if text:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row = await fetch_one(
            "SELECT id FROM document_chunks WHERE chunk_hash = %(h)s LIMIT 1",
            {"h": h},
        )
        if row:
            return str(row["id"])
    return None
