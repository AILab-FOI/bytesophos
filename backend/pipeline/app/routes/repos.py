# app/routes/repos.py

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from fastapi import APIRouter, HTTPException, Query, Depends

from fastapi.responses import FileResponse
from app.schemas.repo import RepoBrief

from app.routes.auth import get_current_user_token
from app.services.file_utils import list_files, read_file
from app.services.pipeline import query_codebase
from app.utils import get_document_store
from app.schemas.query import QueryRequest, RepoQuery
from app.services.progress import BROKER
from app.config import UPLOAD_DIR, DATA_DIR
from app.db import fetch_one, fetch_all, execute

from app.schemas.repo import (
    StatisticsResponse,
    DocumentItem,
    ListDocumentsResponse,
    ContextDoc,
    AnswerRequest,
    AnswerResponse,
    FileContentResponse,
    PhaseState,
    RepoStatusResponse,
)

import shutil

router = APIRouter(tags=["repos"], prefix="/repos")

async def mark_repo_indexed(repo_id: str) -> None:
    """
    Set last_indexed_at and record a lightweight status flag in repos.metadata.
    Safe to call multiple times.
    """
    await execute(
        """
        UPDATE repos
        SET
          last_indexed_at = NOW(),
          metadata = jsonb_set(
            COALESCE(metadata, '{}'::jsonb),
            '{last_index_status}',
            to_jsonb('indexed'::text),
            true
          )
        WHERE id = %(id)s
        """,
        {"id": repo_id},
    )

async def upsert_repo(
    *,
    repo_id: str,
    owner_user_id: Optional[str],
    source_type: str,        
    source_uri: Optional[str],
    storage_path: str,      
    title: Optional[str] = None,
    is_shared: bool = False,
) -> Dict[str, Any]:
    """
    Create or update a repo row. Returns {id, name, title, is_shared}.
    `name` is derived by the DB trigger if not provided.
    """
    row = await fetch_one(
        """
        INSERT INTO repos (id, owner_user_id, source_type, source_uri, storage_path, title, is_shared)
        VALUES (%(id)s, %(owner)s, %(stype)s, %(suri)s, %(spath)s, %(title)s, %(shared)s)
        ON CONFLICT (id) DO UPDATE SET
          owner_user_id = COALESCE(EXCLUDED.owner_user_id, repos.owner_user_id),
          source_type   = EXCLUDED.source_type,
          source_uri    = EXCLUDED.source_uri,
          storage_path  = EXCLUDED.storage_path,
          title         = COALESCE(EXCLUDED.title, repos.title),
          is_shared     = EXCLUDED.is_shared
        RETURNING id, name, title, is_shared
        """,
        {
            "id": repo_id,
            "owner": owner_user_id,
            "stype": source_type,
            "suri": source_uri,
            "spath": storage_path,
            "title": title,
            "shared": is_shared,
        },
    )
    return {"id": row["id"], "name": row["name"], "title": row["title"], "is_shared": row["is_shared"]}

@router.get("/briefs")
async def my_repo_briefs(user_id: str = Depends(get_current_user_token)) -> list[RepoBrief]:
    rows = await fetch_all(
        """
        SELECT
          id,
          COALESCE(NULLIF(btrim(title), ''), NULLIF(btrim(name), ''), id) AS label,
          source_type
        FROM repos
        WHERE owner_user_id = %(owner)s
        ORDER BY created_at DESC
        """,
        {"owner": user_id},
    )
    return [{"id": r["id"], "label": r["label"], "source_type": r["source_type"]} for r in (rows or [])]

@router.post("", summary="Create or update a repo row")
async def create_or_update_repo(
    repo_id: str = Query(..., alias="repoId"),
    source_type: str = Query(..., description="git|upload"),
    source_uri: Optional[str] = Query(None),
    storage_path: str = Query(...),
    title: Optional[str] = Query(None),
    is_shared: bool = Query(False),
    user_id: str = Depends(get_current_user_token),
):
    if source_type not in {"git", "upload"}:
        raise HTTPException(status_code=400, detail="source_type must be 'git' or 'upload'")
    return await upsert_repo(
        repo_id=repo_id,
        owner_user_id=user_id,
        source_type=source_type,
        source_uri=source_uri,
        storage_path=storage_path,
        title=title,
        is_shared=is_shared,
    )

async def _get_repo_row(repo_id: str) -> Optional[Dict[str, Any]]:
    return await fetch_one(
        """
        SELECT id, owner_user_id, name, title, is_shared
        FROM repos
        WHERE id = %(id)s
        """,
        {"id": repo_id},
    )


async def _assert_repo_access(repo_id: str, user_id: str) -> Dict[str, Any]:
    """
    Ensure the caller can access this repo:
      - owner_user_id == user_id, or
      - is_shared = true
    Otherwise raise 404 to avoid leaking repo existence.
    """
    row = await _get_repo_row(repo_id)
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")

    owner = row.get("owner_user_id")
    is_shared = bool(row.get("is_shared"))

    if owner is not None and str(owner) == str(user_id):
        return row
    if is_shared:
        return row

    raise HTTPException(status_code=404, detail="Repository not found")


async def _list_repo_names_for_user(user_id: str) -> Dict[str, str]:
    rows = await fetch_all(
        """
        SELECT id, COALESCE(NULLIF(btrim(title), ''), NULLIF(btrim(name), ''), id) AS label
        FROM repos
        WHERE owner_user_id = %(owner)s
        ORDER BY created_at DESC
        """,
        {"owner": user_id},
    )
    return {r["id"]: r["label"] for r in (rows or [])}

def _repo_filter(repo_id: str) -> dict:
    return {
        "operator": "OR",
        "conditions": [
            {"field": "meta.repo_id", "operator": "==", "value": repo_id},
            {"field": "meta.repoId", "operator": "==", "value": repo_id},
        ],
    }


def _map_broker_to_status(phases: Dict[str, Any]) -> Optional[str]:
    if not phases:
        return None

    def st(name: str) -> str:
        s = phases.get(name) or {}
        return (s.get("status") or "").lower()

    for p in phases.values():
        if isinstance(p, dict) and (p.get("status") or "").lower() == "error":
            return "error"

    running_like = {"queued", "running"}
    if st("upload") in running_like or st("cloning") in running_like:
        return "upload"
    if st("indexing") in running_like or st("embedding") in running_like or st("chunking") in running_like:
        return "indexing"

    return None


def _count_documents(repo_id: str) -> int:
    store = get_document_store()
    docs = store.filter_documents(filters=_repo_filter(repo_id))
    try:
        return len(docs)
    except Exception:
        return sum(1 for _ in docs)


def _repo_dir_exists(repo_id: str) -> bool:
    return (Path(UPLOAD_DIR) / repo_id).exists()


async def _snap_broker(repo_id: str) -> Dict[str, Any]:
    try:
        if BROKER:
            return await BROKER.snapshot(repo_id)
    except Exception:
        pass
    return {}


async def _compute_status(repo_id: str) -> Tuple[str, Dict[str, PhaseState], Dict[str, Any]]:
    if not _repo_dir_exists(repo_id):
        return "missing", {}, {"documents": 0}

    snap: Dict[str, Any] = await _snap_broker(repo_id)
    raw_phases = (snap.get("phases") or {}) if isinstance(snap, dict) else {}
    typed_phases: Dict[str, PhaseState] = {
        k: PhaseState(**v) for k, v in raw_phases.items() if isinstance(v, dict)
    }

    doc_count = _count_documents(repo_id)
    if doc_count > 0:
        return "indexed", typed_phases, {"documents": doc_count}

    broker_status = _map_broker_to_status(raw_phases)
    if broker_status:
        return broker_status, typed_phases, {"documents": doc_count}

    return "new", typed_phases, {"documents": doc_count}


@router.get("/names")
async def my_repo_names(user_id: str = Depends(get_current_user_token)) -> Dict[str, str]:
    """
    Return ONLY the current user's repos as { repoId: name_or_title }.
    """
    return await _list_repo_names_for_user(user_id)


@router.get("/{repo_id}/status", response_model=RepoStatusResponse)
async def get_status(repo_id: str, user_id: str = Depends(get_current_user_token)):
    await _assert_repo_access(repo_id, user_id)

    if not _repo_dir_exists(repo_id):
        raise HTTPException(status_code=404, detail="Repository not found")

    status, typed, stats = await _compute_status(repo_id)
    return RepoStatusResponse(repoId=repo_id, status=status, phases=typed, stats=stats)


@router.get("/{repo_id}/files", response_model=List[str])
def get_files(repo_id: str, user_id: str = Depends(get_current_user_token)):
    raise_http = False
    repo_path = Path(UPLOAD_DIR) / repo_id
    if not repo_path.is_dir():
        raise HTTPException(status_code=404, detail="Repository not found")
    return list_files(repo_id)


@router.get(
    "/{repo_id}/file",
    response_model=FileContentResponse,
    responses={404: {"description": "File not found"}},
)
def get_file(
    repo_id: str,
    path: str = Query(..., description="Relative path to file in the repo"),
    user_id: str = Depends(get_current_user_token),
):
    repo_dir = (Path(UPLOAD_DIR) / repo_id).resolve()
    file_path = (repo_dir / path).resolve()
    if not str(file_path).startswith(str(repo_dir)) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = read_file(repo_id, path)
    except Exception:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            raise HTTPException(status_code=404, detail="File not found")
    return FileContentResponse(content=content)


@router.get("/{repo_id}/queries", response_model=List[RepoQuery])
def get_queries(repo_id: str, user_id: str = Depends(get_current_user_token)):
    qpath = Path(DATA_DIR) / repo_id / "queries.json"
    if not qpath.exists():
        return []
    import json
    data = json.loads(qpath.read_text(encoding="utf-8"))
    return [RepoQuery(**item) for item in data]


@router.get("/statistics", response_model=StatisticsResponse)
async def statistics(
    repoId: str = Query(..., alias="repoId", description="Repository ID"),
    user_id: str = Depends(get_current_user_token),
):
    await _assert_repo_access(repoId, user_id)

    if not _repo_dir_exists(repoId):
        return StatisticsResponse(index_status="missing", document_count=0)

    status, _typed, stats = await _compute_status(repoId)
    return StatisticsResponse(
        index_status=status,
        document_count=int(stats.get("documents", 0)),
    )

@router.delete("/{repo_id}", summary="Delete a repository and its data")
async def delete_repo(repo_id: str, user_id: str = Depends(get_current_user_token)):
    """
    Hard-delete the repo:
      - verify access
      - delete conversations referencing this repo (if such a table exists)
      - delete the repo row
      - best-effort remove uploaded files on disk
    """
    await _assert_repo_access(repo_id, user_id)

    try:
        await execute("DELETE FROM conversations WHERE repo_id = %(id)s", {"id": repo_id})
    except Exception:
        pass

    deleted = await fetch_one(
        """
        DELETE FROM repos
         WHERE id = %(id)s AND (owner_user_id = %(owner)s OR is_shared = TRUE)
     RETURNING id
        """,
        {"id": repo_id, "owner": user_id},
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(UPLOAD_DIR) / repo_id
    try:
        shutil.rmtree(repo_path, ignore_errors=True)
    except Exception:
        pass

    return {"status": "deleted", "repoId": repo_id}

@router.get("/list_documents", response_model=ListDocumentsResponse)
async def list_documents(
    repoId: str = Query(..., alias="repoId", description="Repository ID"),
    user_id: str = Depends(get_current_user_token),
):
    await _assert_repo_access(repoId, user_id)

    store = get_document_store()
    docs = store.filter_documents(filters=_repo_filter(repoId))
    items = [DocumentItem(id=d.id, content=d.content, meta=d.meta or {}) for d in docs]
    return ListDocumentsResponse(documents=items)


@router.post("/answer", response_model=AnswerResponse, status_code=200)
async def answer(req: AnswerRequest, user_id: str = Depends(get_current_user_token)):
    repo_id = (req.repo_id or req.repoId or "").strip()
    question = (req.query or req.question or "").strip()
    conv_id = (req.conversation_id or req.conversationId or "") or None
    user_from_req = (req.user_id or req.userId or "") or None

    if not repo_id or not question:
        raise HTTPException(status_code=422, detail="Both repo_id (or repoId) and query (or question) are required.")

    await _assert_repo_access(repo_id, user_id)

    qr = QueryRequest(
        repoId=repo_id,
        question=question,
        conversationId=conv_id,
        userId=user_from_req or user_id,
    )

    answer_text, contexts = await query_codebase(qr, filters=_repo_filter(repo_id))

    return AnswerResponse(
        answer=answer_text,
        contexts=[ContextDoc(filename=c["filename"], content=c["content"], id=c.get("id")) for c in contexts],
    )


from fastapi.responses import FileResponse

@router.get("/{repo_id}/raw")
def get_file_raw(
    repo_id: str,
    path: str = Query(..., description="Relative path to file in the repo"),
    user_id: str = Depends(get_current_user_token),
):
    _ = asyncio.run(_assert_repo_access(repo_id, user_id)) if False else None
    repo_dir = (Path(UPLOAD_DIR) / repo_id).resolve()
    file_path = (repo_dir / path).resolve()
    if not str(file_path).startswith(str(repo_dir)) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)