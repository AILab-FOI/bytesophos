# app/utils.py

from pathlib import Path
from typing import List, Dict, Any, Optional

from haystack.utils import Secret
from haystack import Document
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.embedders.voyage_embedders import (
    VoyageDocumentEmbedder,
    VoyageTextEmbedder,
)

from app.chunking import chunk_code
from app.services.file_utils import list_files
from app.config import (
    DATABASE_DSN,            
    UPLOAD_DIR,            
    EMBEDDINGS_INDEX,    
    VOYAGE_EMBED_MODEL,   
)

UPLOADS = Path(UPLOAD_DIR).resolve()

EMBEDDINGS_TABLE = EMBEDDINGS_INDEX
DEFAULT_EMBED_DIM = 1536

def get_document_store(
    recreate: bool = False,
    embedding_dimension: Optional[int] = None,
) -> PgvectorDocumentStore:
    """
    Return a PgvectorDocumentStore consistent with the one used in indexing.py.
    NOTE: indexing.py lazily creates the table when it knows the model's true dim.
    Here, fallback is to DEFAULT_EMBED_DIM if not provided.
    """
    dim = embedding_dimension or DEFAULT_EMBED_DIM
    return PgvectorDocumentStore(
        connection_string=Secret.from_token(DATABASE_DSN),
        table_name=EMBEDDINGS_TABLE,
        embedding_dimension=dim,
        create_extension=True,
        recreate_table=recreate,
        search_strategy="hnsw",
        hnsw_recreate_index_if_exists=False,
        hnsw_index_creation_kwargs={"M": 16, "ef_construction": 200},
        hnsw_index_name="haystack_hnsw_index",
        hnsw_ef_search=50,
    )


def _skip_hidden(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    return any(p.startswith(".") for p in parts if p)


def load_code_chunks(repo_id: str) -> List[Document]:
    repo_path = (UPLOADS / repo_id).resolve()
    if not repo_path.is_dir():
        return []

    docs: List[Document] = []
    for rel_path in list_files(repo_id):
        if _skip_hidden(rel_path):
            continue

        abs_path = (repo_path / rel_path).resolve()
        try:
            if not str(abs_path).startswith(str(repo_path)) or not abs_path.is_file():
                continue
        except Exception:
            continue

        try:
            text = abs_path.read_text(encoding="utf-8")
        except Exception:
            continue

        for idx, ch in enumerate(chunk_code(rel_path, text)):
            content = (ch.get("content") or "").strip()
            if not content:
                continue
            docs.append(
                Document(
                    content=content,
                    meta={
                        "repo_id": repo_id,
                        "filename": rel_path,
                        "chunk_index": idx,
                        "start_line": ch.get("start_line"),
                        "end_line": ch.get("end_line"),
                    },
                )
            )
    return docs


def index_repo(repo_id: str, *, batch_size: int = 16, max_chars: int = 10000, overlap: int = 200) -> Dict[str, Any]:
    repo_dir = (UPLOADS / repo_id).resolve()
    if not repo_dir.is_dir():
        return {"status": "error", "detail": "Repository not found"}

    from app.services.indexing import index_repo as _index_repo
    _index_repo(str(repo_dir), repo_id, batch_size=batch_size, max_chars=max_chars, overlap=overlap)
    return {"status": "started", "repo_id": repo_id}


def get_query_embedder() -> VoyageTextEmbedder:
    return VoyageTextEmbedder(
        model=VOYAGE_EMBED_MODEL,
        input_type="query",
    )


def backfill_embeddings(batch_size: int = 32) -> int:
    store = get_document_store()
    embedder = VoyageDocumentEmbedder(model=VOYAGE_EMBED_MODEL, input_type="document")
    try:
        embedder.warm_up()
    except Exception:
        pass
    store.update_embeddings(embedder, batch_size=batch_size, index=EMBEDDINGS_TABLE)
    return 0
