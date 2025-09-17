# app/routes/upload.py

from pathlib import Path
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    UploadFile,
    HTTPException,
    Form,
    File,
    Depends,
)

import aiofiles

from app.routes.auth import get_current_user_token
from app.config import UPLOAD_DIR
from app.routes import repos as repos_routes
from app.services.upload import handle_github_clone, handle_zip_upload_from_path

router = APIRouter(tags=["upload"])


@router.post("/upload", status_code=202)
async def upload_repo(
    background_tasks: BackgroundTasks,
    type: str = Form(..., description="Either 'github' or 'zip'"),
    repo_url: str | None = Form(None, description="GitHub URL, when type=github"),
    file: UploadFile | None = File(None, description="ZIP file, when type=zip"),
    user_id: str = Depends(get_current_user_token),
):
    """
    Start a repo ingest in the background and register a row in `repos`.
    Always returns 202 + {repoId}.
    """
    kind = (type or "").strip().lower()
    if kind not in {"github", "zip"}:
        raise HTTPException(
            status_code=400, detail="Unknown upload type (use 'github' or 'zip')."
        )

    repo_id = uuid.uuid4().hex
    source_type = "git" if kind == "github" else "upload"
    source_uri = (repo_url or "").strip() if kind == "github" else None
    storage_path = str(Path(UPLOAD_DIR) / repo_id)

    await repos_routes.upsert_repo(
        repo_id=repo_id,
        owner_user_id=user_id,
        source_type=source_type,
        source_uri=source_uri,
        storage_path=storage_path,
        title=None,
        is_shared=False,
    )

    if kind == "github":
        if not source_uri:
            raise HTTPException(
                status_code=400, detail="Missing repo_url for GitHub upload"
            )
        background_tasks.add_task(handle_github_clone, source_uri, repo_id, owner_user_id=user_id)
        return {"repoId": repo_id}

    if file is None:
        raise HTTPException(status_code=400, detail="Missing file for ZIP upload")

    repo_dir = Path(UPLOAD_DIR) / repo_id
    repo_dir.mkdir(parents=True, exist_ok=True)

    original_name = (file.filename or f"{repo_id}.zip").strip()
    if not original_name.lower().endswith(".zip"):
        original_name += ".zip"

    final_zip_path = repo_dir / original_name
    tmp_zip_path = final_zip_path.with_suffix(final_zip_path.suffix + ".part")

    try:
        chunk_size = 1024 * 1024
        async with aiofiles.open(tmp_zip_path, "wb") as out_f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                await out_f.write(chunk)
    except Exception as e:
        try:
            if tmp_zip_path.exists():
                tmp_zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to receive ZIP: {e}")

    try:
        tmp_zip_path.replace(final_zip_path)
    except Exception as e:
        try:
            if final_zip_path.exists():
                final_zip_path.unlink(missing_ok=True)
            tmp_zip_path.rename(final_zip_path)
        except Exception as e2:
            try:
                if tmp_zip_path.exists():
                    tmp_zip_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Failed to finalize ZIP: {e2}") from e

    background_tasks.add_task(
        handle_zip_upload_from_path,
        str(final_zip_path),
        repo_id,
        owner_user_id=user_id,
    )

    return {"repoId": repo_id}
