# app/services/languages.py

from __future__ import annotations
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from tree_sitter import Parser
from tree_sitter_languages import get_language

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "c_sharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".ex": "elixir",
    ".exs": "elixir",
    ".el": "elisp",
    ".ml": "ocaml",
    ".r": "r",
    ".elm": "elm",
    ".ql": "ql",
}

def extension_to_language(ext_or_path: str) -> Optional[str]:
    """Return tree-sitter language name for a file extension or path."""
    ext = ext_or_path
    if not ext.startswith("."):
        ext = Path(ext_or_path).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext.lower())

@lru_cache(maxsize=None)
def get_parser(language_name: str) -> Optional[Parser]:
    """Cached Parser for a tree-sitter language name."""
    try:
        lang = get_language(language_name)
        p = Parser()
        p.set_language(lang)
        return p
    except Exception as exc:
        logging.warning("Failed to create parser for %s: %s", language_name, exc)
        return None

def get_parser_for_path(path: str) -> Optional[Parser]:
    """Get a cached Parser based on the file path’s extension."""
    lang = extension_to_language(path)
    return get_parser(lang) if lang else None
