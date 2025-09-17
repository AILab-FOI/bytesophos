# eval/generate_eval_dataset.py

import os
import re
import json
import random
import string
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from chunking import chunk_code

THIS_DIR = Path(__file__).resolve().parent
REPO_SRC_ROOT = THIS_DIR / "laGGer" 
TREE_PATH = THIS_DIR / "data/repos/repo_tree.txt"
OUT_PATH = THIS_DIR / "data/eval/lagger_test_data.json"
DUMP_JSONL = THIS_DIR / "data/eval/chunks_dump.jsonl"
DUMP_MD = THIS_DIR / "data/eval/chunks_preview.md"
TOTAL_ITEMS = int(os.getenv("RAGAS_TESTSET_SIZE", "200"))
SHOW_CHUNKS = os.getenv("SHOW_CHUNKS", "1") == "1"

# assisted with ChatGPT 5
ALLOW_EXT = {
    ".py",".js",".jsx",".ts",".tsx",".java",".go",".rb",".rs",".php",".c",".h",".cpp",".hpp",
    ".cs",".kt",".swift",".m",".mm",".sql",".r",".pl",".scala",".sh",".bash",".ps1",
    ".yaml",".yml",".toml",".ini",".cfg",".json",".md"
}

_TREE_RUNE_RE = re.compile(r"[│├└─]+")

# assisted with ChatGPT 5
def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")

# assisted with ChatGPT 5
def trim(s: str, lim: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= lim else s[:lim] + "\n...<truncated>..."

# assisted with ChatGPT 5
def parse_paths_from_tree(tree_text: str) -> List[str]:
    """
    Parse file paths from a `tree`-like text file. Ignores directories and .git entries.
    """
    out = []
    for raw in tree_text.splitlines():
        line = _TREE_RUNE_RE.sub("", raw).lstrip()
        if not line or line.endswith("/") or line.endswith(":"):
            continue
        if line.startswith("./"):
            line = line[2:]
        if line.startswith(".git") or line.endswith(".pyc"):
            continue
        out.append(line)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq

def list_repo_files(repo_root: Path) -> List[str]:
    """
    Fallback: walk the repo to collect files if TREE_PATH is missing.
    """
    out: List[str] = []
    for p in repo_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in ALLOW_EXT:
            out.append(str(p.relative_to(repo_root)))
    return out

def safe_read_file(p: Path) -> Optional[str]:
    try:
        if not p.exists() or not p.is_file():
            return None
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

# assisted with ChatGPT 5
_THINK_RE = re.compile(r"(?is)<\s*think\s*>.*?<\s*/\s*think\s*>")
_FOLLOWUP_RE = re.compile(r"(?im)^\s*(follow-?up( question)?|next steps|what next)\s*:.*$", re.MULTILINE)

# assisted with ChatGPT 5
def clean_for_dataset(text: str) -> str:
    if not text:
        return ""
    text = _THINK_RE.sub("", text)
    text = _FOLLOWUP_RE.sub("", text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

SYS_PROMPT_TMPL = string.Template(
    """You generate concise Q/A pairs grounded ONLY in the provided code chunk.

Absolute rules
- Every question must be answerable from the chunk as-is (no external files, no internet, no guesses).
- Prefer specific, developer-style questions (APIs, params, return values, side effects, filenames, env vars).
- Answers can be:
  • Plain answers: 1-3 sentences.
  • Code answers: include a **verbatim** snippet copied from the chunk inside a fenced block (```<language> ... ```),
    followed by one short sentence explaining it.
- Snippets must be copied directly from the chunk (no invented code, no pseudo-code) and may be any length that is natural
  to the context (no artificial line limit).
- Do NOT include chain-of-thought or <think> sections - provide only the final answer/snippet.

Return ONLY a JSON object with this schema:
{
  "samples": [
    {"question": "...", "answer": "..."}
  ]
}

Generate between ${nmin} and ${nmax} samples depending on chunk richness.
"""
)

HUMAN_TMPL = """Repository tree (context only; do NOT invent files beyond this):
{tree}

File: {path}
Lines: {start_line}-{end_line}

Code chunk:
{chunk}

Return ONLY the JSON object, no commentary.
"""

def call_llm_json(
    llm: ChatGroq,
    tree_text: str,
    chunk_text: str,
    nmin=2,
    nmax=6,
    file_path: str = "",
    span: Tuple[int, int] = (1, 1),
    retries=2
) -> List[Dict[str, str]]:
    sys_msg = SystemMessage(content=SYS_PROMPT_TMPL.substitute(nmin=nmin, nmax=nmax))
    human = HumanMessage(content=HUMAN_TMPL.format(
        tree=trim(tree_text, 2000),
        path=file_path,
        start_line=span[0],
        end_line=span[1],
        chunk=chunk_text
    ))

    for _ in range(retries + 1):
        resp = llm.invoke([sys_msg, human])
        text = (resp.content or "").strip()
        try:
            start, end = text.find("{"), text.rfind("}")
            obj = json.loads(text[start:end+1])
            out = []
            for s in obj.get("samples", []):
                q = (s.get("question") or "").strip()
                a = clean_for_dataset((s.get("answer") or ""))
                if q and a:
                    out.append({"question": q, "reference": a})
            if out:
                return out
        except Exception:
            continue
    return []

def iter_code_chunks(
    repo_root: Path,
    file_paths: List[str],
    max_chars: int = 10_000,
    overlap: int = 200
):
    """
    Iterate code chunks using your programming-aware chunker.
    Emits (relative_path, content, start_line, end_line).
    Also records a human preview dump (first ~40 lines) if SHOW_CHUNKS=1.
    """
    stats = {"seen": 0, "skip_ext": 0, "skip_empty": 0, "kept_chunks": 0}
    previews: List[Dict[str, str]] = []

    for rel in file_paths:
        stats["seen"] += 1
        p = repo_root / rel
        if p.suffix.lower() not in ALLOW_EXT:
            stats["skip_ext"] += 1
            continue
        text = safe_read_file(p)
        if not text:
            stats["skip_empty"] += 1
            continue

        try:
            pieces = chunk_code(str(p), text, max_chars=max_chars, overlap=overlap)
        except Exception:
            continue

        for ch in pieces:
            content = (ch.get("content") or "").strip()
            s = int(ch.get("start_line") or 1)
            e = int(ch.get("end_line") or s)
            if content:
                stats["kept_chunks"] += 1
                previews.append({
                    "path": str(p.relative_to(repo_root)),
                    "start_line": s,
                    "end_line": e,
                    "preview": "\n".join(content.splitlines()[:40])
                })
                yield str(p.relative_to(repo_root)), content, s, e

    if SHOW_CHUNKS:
        DUMP_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with DUMP_JSONL.open("w", encoding="utf-8") as f:
            for pr in previews:
                f.write(json.dumps(pr, ensure_ascii=False) + "\n")
        with DUMP_MD.open("w", encoding="utf-8") as f:
            f.write("# Chunk preview\n\n")
            for pr in previews:
                f.write(f"## {pr['path']} (lines {pr['start_line']}-{pr['end_line']})\n\n")
                f.write("```text\n")
                f.write(pr["preview"])
                f.write("\n```\n\n")
        print(
            f"[chunks] seen={stats['seen']} kept={stats['kept_chunks']} "
            f"skip_ext={stats['skip_ext']} skip_empty={stats['skip_empty']}"
        )
        print(f"[chunks] Dumped → {DUMP_MD}")

def main():
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("Set GROQ_API_KEY")

    if TREE_PATH.exists():
        tree_text = read_text(TREE_PATH)
        rel_paths = parse_paths_from_tree(tree_text)
    else:
        tree_text = "(no tree file; walking repository)"
        rel_paths = list_repo_files(REPO_SRC_ROOT)

    chunks_list = list(iter_code_chunks(REPO_SRC_ROOT, rel_paths))
    if not chunks_list:
        raise RuntimeError("No chunks produced from repo")

    base_model = os.getenv("GROQ_MODEL", "qwen/qwen3-32b")
    random.shuffle(chunks_list)

    target = TOTAL_ITEMS
    items: List[Dict[str, str]] = []
    seen = set()
    loop = 0

    unique_files = len({p for p, _, _, _ in chunks_list})
    print(f"[info] Target size={target}, files={unique_files}, chunks={len(chunks_list)}")

    while len(items) < target and loop < 50:
        temp = 0.2 + (0.02 * loop % 0.4)
        llm = ChatGroq(model=base_model, temperature=temp)

        for path, content, s, e in chunks_list:
            if len(items) >= target:
                break
            nmax = 8 if len(content) > 900 else 6 if len(content) > 500 else 4
            nmin = max(1, nmax - 2)
            samples = call_llm_json(
                llm, tree_text, content, nmin=nmin, nmax=nmax, file_path=path, span=(s, e)
            )
            for srow in samples:
                if len(items) >= target:
                    break
                key = re.sub(r"\s+", " ", srow["question"].lower())
                if key in seen:
                    continue
                items.append({"question": srow["question"], "reference": srow["reference"]})
                seen.add(key)
        loop += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(items[:target], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[done] Wrote {len(items[:target])} examples → {OUT_PATH}")

if __name__ == "__main__":
    main()
