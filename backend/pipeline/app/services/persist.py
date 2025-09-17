# app/services/persist.py

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.db import fetch_one, execute
from app.services.chunks import resolve_chunk_id

def append_local_history(repo_id: str, question: str, answer: str) -> None:
    repo_dir = Path("data") / "repos" / repo_id
    repo_dir.mkdir(parents=True, exist_ok=True)
    hist_file = repo_dir / "queries.json"
    history = json.loads(hist_file.read_text(encoding="utf-8")) if hist_file.exists() else []
    history.append({
        "question": question,
        "answer": answer,
        "timestamp": datetime.utcnow().isoformat(),
    })
    hist_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

async def persist_query_and_chunks(
    conversation_id: Optional[str],
    user_id: Optional[str],
    question: str,
    answer: str,
    retrieved_docs: List,
    response_metadata: Dict,
) -> None:
    try:
        rq = await fetch_one(
            """
            INSERT INTO rag_queries (conversation_id, user_id, query_text, response_text, response_metadata)
            VALUES (%(conversation_id)s, %(user_id)s, %(query_text)s, %(response_text)s, %(response_metadata)s::jsonb)
            RETURNING id
            """,
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "query_text": question,
                "response_text": answer,
                "response_metadata": json.dumps(response_metadata),
            },
        )
        if not rq or "id" not in rq:
            raise RuntimeError("INSERT rag_queries did not return an id")

        rag_query_id = rq["id"]

        try:
            rank_counter = 1
            for d in retrieved_docs:
                meta = getattr(d, "meta", {}) or {}
                content = getattr(d, "content", "") or ""
                score = getattr(d, "score", None)

                dc_id = await resolve_chunk_id(meta, content)
                if not dc_id:
                    rank_counter += 1
                    continue

                await execute(
                    """
                    INSERT INTO retrieved_chunks (id, rag_query_id, document_chunk_id, score, rank, used_in_prompt, created_at)
                    VALUES (gen_random_uuid(), %(rq_id)s, %(dc_id)s, %(score)s, %(rank)s, TRUE, now())
                    """,
                    {
                        "rq_id": rag_query_id,
                        "dc_id": dc_id,
                        "score": float(score) if isinstance(score, (int, float)) else None,
                        "rank": rank_counter,
                    },
                )
                rank_counter += 1
        except Exception as e_chunks:
            print("[warn] Failed to persist retrieved_chunks:", repr(e_chunks))
            traceback.print_exc()

    except Exception as e:
        print("[warn] Failed to persist RAG query/chunks:", repr(e))
        traceback.print_exc()