# app/services/prompts.py

from typing import List, Tuple
from jinja2 import Template

def system_rules() -> str:
        return (
        "You are a coding RAG assistant.\n"
        "- Cite sources by filename + line ranges only (e.g., `src/utils.py` lines 120–180).\n"
        "- NEVER refer to sources as “Document N”.\n"
        "- Use EXACT identifiers (class/function/file names) from the context, wrapped in backticks.\n"
        "- If multiple excerpts are from the same file, synthesize across them as one.\n"
        "- If a name/reference is ambiguous, say it is unclear - do NOT guess or invent.\n"
        "- Answer concisely first, then offer three short relevant follow-up help questions."
    )

_CURRENT_USER_TPL = Template(
    """{{ warning }}You are assisting with the repository: `{{ repo_id }}`.

{% if history_md -%}
Earlier conversation (most recent last). Use only if relevant:
{{ history_md }}

{%- endif %}
Context (grouped by file):
{% for fname, body in grouped_files -%}
FILE: {{ fname }}
{{ body }}

{% endfor -%}

Question: {{ question }}

Respond with citations (filename + line ranges only)."""
)

def render_current_user_payload(
    repo_id: str,
    history_md: str,
    grouped_files: List[Tuple[str, str]],
    question: str,
    warning: str = "",
) -> str:
    return _CURRENT_USER_TPL.render(
        warning=warning,
        repo_id=repo_id,
        history_md=history_md,
        grouped_files=grouped_files,
        question=question,
    )
