# app/services/pipeline.py

import json
import traceback
from typing import Dict, List, Tuple, Optional

from haystack.dataclasses import ChatMessage

from app.config import VOYAGE_RERANK_MODEL
from app.schemas.query import QueryRequest
from app.services.retrieval import build_retrieval_pipeline, run_retrieval
from app.services.history import load_recent_history, render_history_md, history_hint, compact
from app.services.prompts import system_rules, render_current_user_payload
from app.services.chunks import rewrite_doc_numbers_to_filenames
from app.services.persist import append_local_history, persist_query_and_chunks
from app.db import fetch_one

async def query_codebase(
    request: QueryRequest,
    filters: Optional[Dict] = None,
) -> Tuple[str, List[Dict]]:
    """
    Run retrieval + LLM with history-aware chat and return (answer, contexts).
    Persists the turn into rag_queries + retrieved_chunks.
    """
    pipe = build_retrieval_pipeline()

    recent_turns = await load_recent_history(getattr(request, "conversationId", None), limit=6)
    history_md = render_history_md(recent_turns)
    hint = history_hint(recent_turns)

    retriever_query = request.question
    if hint:
        retriever_query = f"{request.question}\n\n(History hint: {hint})"

    retrieved, contexts, grouped_files, file_order, warning = run_retrieval(
        pipe, retriever_query, filters
    )

    sys_rules = system_rules()
    current_user_payload = render_current_user_payload(
        repo_id=request.repoId,
        history_md=history_md,
        grouped_files=grouped_files,
        question=request.question,
        warning=warning,
    )

    messages: List[ChatMessage] = [ChatMessage.from_system(sys_rules)]
    if recent_turns:
        for t in reversed(recent_turns):
            messages.append(ChatMessage.from_user(compact(t.get("query_text", ""), 1000)))
            messages.append(ChatMessage.from_assistant(compact(t.get("response_text", ""), 1400)))
    messages.append(ChatMessage.from_user(current_user_payload))

    streamed_chunks: List[str] = []

    def on_chunk(chunk) -> None:
        text = getattr(chunk, "content", None)
        if not text:
            try:
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    text = getattr(getattr(choices[0], "delta", {}), "content", "") or getattr(choices[0], "text", "")
            except Exception:
                text = ""
        if text:
            print(text, end="", flush=True)
            streamed_chunks.append(text)

    from app.services.llm_client import build_llm
    llm = build_llm(on_chunk)
    llm_result = llm.run(messages)

    answer = "".join(streamed_chunks).strip()
    if not answer:
        replies = llm_result.get("replies", [])
        if replies:
            answer = getattr(replies[0], "text", str(replies[0])) or ""

    answer = rewrite_doc_numbers_to_filenames(answer, file_order)

    append_local_history(request.repoId, request.question, answer)

    try:
        print(f"[dbg] conversationId={getattr(request, 'conversationId', None)} userId={getattr(request, 'userId', None)} repoId={request.repoId}")

        conv_ok = False
        conv_id_param: Optional[str] = None
        conv_user_id: Optional[str] = None

        if getattr(request, "conversationId", None):
            conv_row = await fetch_one(
                "SELECT id, user_id FROM conversations WHERE id = %(id)s",
                {"id": request.conversationId},
            )
            if conv_row:
                conv_ok = True
                conv_id_param = conv_row["id"]
                conv_user_id = conv_row.get("user_id")

        if not conv_ok and getattr(request, "conversationId", None):
            print(f"[warn] conversationId {request.conversationId} not found; inserting rag_query with NULL conversation_id")

        user_id_param: Optional[str] = getattr(request, "userId", None) or conv_user_id

        await persist_query_and_chunks(
            conversation_id=conv_id_param,
            user_id=user_id_param,
            question=request.question,
            answer=answer,
            retrieved_docs=retrieved,
            response_metadata={
                "repo_id": request.repoId,
                "ranker_model": VOYAGE_RERANK_MODEL,
                "retrieved_count": len(retrieved),
            },
        )

    except Exception as e:
        print("[warn] Failed to persist RAG query/chunks:", repr(e))
        traceback.print_exc()

    return answer, contexts
