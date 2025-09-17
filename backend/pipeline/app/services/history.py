# app/services/history.py

import re as _re
from typing import Dict, List, Optional, Tuple

from app.db import fetch_one
from app.config import (
    MODEL_CONTEXT_TOKENS,
    TOKENS_PER_CHAR,
    HISTORY_BUDGET_FRACTION,
    SAFETY_MARGIN_TOKENS,
    MAX_HISTORY_TOKENS,
)

async def load_recent_history(conversation_id: Optional[str], limit: int = 12) -> List[Dict]:
    """
    Newest-first turns: [{ query_text, response_text, created_at }, ...]
    """
    if not conversation_id:
        return []
    rows = await fetch_one(
        """
        SELECT json_agg(t.* ORDER BY t.created_at DESC) AS items
        FROM (
          SELECT query_text, response_text, created_at
          FROM rag_queries
          WHERE conversation_id = %(cid)s
          ORDER BY created_at DESC
          LIMIT %(lim)s
        ) t
        """,
        {"cid": conversation_id, "lim": limit},
    )
    return (rows.get("items") if rows else []) or []

def _chars_for_tokens(tokens: int) -> int:
    return max(0, int(tokens / max(TOKENS_PER_CHAR, 1e-6)))

def _tokens_for_chars(chars: int) -> int:
    return max(0, int(chars * TOKENS_PER_CHAR))

def compact(text: str, max_chars: Optional[int]) -> str:
    """
    Compaction used ONLY for LLM message injection.
    Pass max_chars=None to DISABLE truncation.
    """
    if not text:
        return ""
    s = text.strip()
    s = _re.sub(r"```.*?```", "[code omitted]", s, flags=_re.DOTALL)
    s = _re.sub(r"\s+", " ", s)
    if max_chars is None:
        return s
    return (s[: max_chars - 1] + "…") if len(s) > max_chars else s

def render_history_md(turns: List[Dict]) -> str:
    """Full markdown (oldest → newest), no omissions for user-facing summaries."""
    if not turns:
        return ""
    buf: List[str] = []
    for t in reversed(turns):
        q = t.get("query_text", "") or ""
        a = t.get("response_text", "") or ""
        buf.append(f"- **User earlier**: {q}\n  **Assistant earlier**: {a}")
    return "\n".join(buf)

def history_hint(turns: List[Dict]) -> str:
    """Latest user query (no cap)."""
    if not turns:
        return ""
    latest = turns[0]
    return _re.sub(r"\s+", " ", latest.get("query_text", "") or "").strip()

def compute_history_budget_tokens(
    ctx_tokens: int = MODEL_CONTEXT_TOKENS,
    history_fraction: float = HISTORY_BUDGET_FRACTION,
    safety_margin: int = SAFETY_MARGIN_TOKENS,
) -> Optional[int]:
    """
    Returns a token budget for history, or None to disable truncation entirely
    if MAX_HISTORY_TOKENS is None.
    """
    if MAX_HISTORY_TOKENS is None:
        return None
    dynamic_budget = max(0, int(ctx_tokens * history_fraction) - safety_margin)
    return min(MAX_HISTORY_TOKENS, dynamic_budget)

def select_and_compact_history_messages(
    turns_newest_first: List[Dict],
    per_turn_soft_cap_chars: Optional[int],
    total_budget_tokens: Optional[int],
) -> List[Tuple[str, str]]:
    """
    Build a list of (user_text, assistant_text) pairs, oldest→newest,
    compacted to fit within total_budget_tokens (approx, via chars heuristic).
    If total_budget_tokens is None, include everything with no truncation.
    """
    if not turns_newest_first:
        return []

    pairs_oldest_first: List[Tuple[str, str]] = []
    for t in reversed(turns_newest_first):
        q = t.get("query_text", "") or ""
        a = t.get("response_text", "") or ""
        pairs_oldest_first.append((q, a))

    if total_budget_tokens is None:
        out: List[Tuple[str, str]] = []
        for q, a in pairs_oldest_first:
            cq = compact(q, per_turn_soft_cap_chars)
            ca = compact(a, per_turn_soft_cap_chars)
            out.append((cq, ca))
        return out

    total_budget_chars = _chars_for_tokens(total_budget_tokens)
    used_chars = 0
    packed: List[Tuple[str, str]] = []
    for q, a in pairs_oldest_first:
        cq = compact(q, per_turn_soft_cap_chars)
        ca = compact(a, per_turn_soft_cap_chars)
        chunk = cq + ca
        need = len(chunk)
        if used_chars + need > total_budget_chars and packed:
            break
        packed.append((cq, ca))
        used_chars += need
    return packed