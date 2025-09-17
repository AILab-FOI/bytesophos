# app/services/upload.py

"""
Handle repository uploads from either GitHub URLs or ZIP files.

This module takes care of:
  * Cloning GitHub repositories.
  * Receiving and extracting uploaded ZIP files.
  * Broadcasting progress updates for the UI.
  * Triggering background indexing after the upload finishes.
  * Keeping the `repos` table in sync (create/update + mark indexed).

Progress updates are sent with `_broadcast` and include phases like:
  - upload
  - embedding
  - indexing
  - indexed
  - error
"""

import os
import re
import zipfile
import asyncio
import logging
from typing import Optional

import aiofiles
from fastapi import UploadFile
from git import Repo, RemoteProgress, GitCommandError

from app.services.indexing import index_repo
from app.services.ws import _broadcast
from app.routes.repos import upsert_repo, mark_repo_indexed
from app.config import UPLOAD_DIR

logger = logging.getLogger(__name__)

os.makedirs(UPLOAD_DIR, exist_ok=True)

GITHUB_URL_RE = re.compile(
    r'^(https?://)?(www\.)?github\.com/[\w\-_]+/[\w\-_]+(\.git)?/?$',
    re.IGNORECASE,
)

_OP_NAME = {
    RemoteProgress.COUNTING:    "Counting objects",
    RemoteProgress.COMPRESSING: "Compressing objects",
    RemoteProgress.RECEIVING:   "Receiving objects",
    RemoteProgress.RESOLVING:   "Resolving deltas",
    RemoteProgress.WRITING:     "Writing objects",
}


def _emit_phase(repo_id: str, phase: str, *, status: str, progress: Optional[int] = None, **extra) -> None:
    """Send a single progress event over WebSocket."""
    payload = {"phase": phase, "status": status}
    if progress is not None:
        payload["progress"] = max(0, min(100, int(progress)))
    payload.update(extra)
    _broadcast(repo_id, payload)


class GitCloneProgress(RemoteProgress):
    """Helper to forward git clone progress to WebSocket."""
    def __init__(self, repo_id: str):
        super().__init__()
        self.repo_id = repo_id
        self._last_pct = -1

    def update(self, op_code, cur_count, max_count=None, message=""):
        op_key = op_code & self.OP_MASK
        op_name = _OP_NAME.get(op_key, "Cloning")

        if op_code & self.BEGIN:
            _emit_phase(self.repo_id, "upload", status="running", progress=0, message=f"Starting {op_name}", kind="github")

        if max_count:
            pct = int(cur_count / max_count * 100) if max_count else None
            if pct is not None and pct != self._last_pct:
                self._last_pct = pct
                _emit_phase(self.repo_id, "upload", status="running", progress=pct, message=f"{op_name} ({pct}%)", kind="github")
        else:
            if message:
                _emit_phase(self.repo_id, "upload", status="running", message=message, kind="github")

        if op_code & self.END:
            _emit_phase(self.repo_id, "upload", status="running", progress=100, message=f"{op_name} complete", kind="github")


async def handle_github_clone(repo_url: str, repo_id: str, *, owner_user_id: Optional[str] = None) -> None:
    """Clone a public GitHub repository and start indexing it."""
    ru = (repo_url or "").strip()
    if not GITHUB_URL_RE.match(ru):
        _emit_phase(repo_id, "upload", status="error", message="Invalid GitHub URL. Expected format https://github.com/user/repo")
        return

    dest = os.path.join(UPLOAD_DIR, repo_id)
    os.makedirs(dest, exist_ok=True)

    try:
        await upsert_repo(
            repo_id=repo_id,
            owner_user_id=owner_user_id,
            source_type="git",
            source_uri=ru,
            storage_path=dest,
            title=None,
            is_shared=False,
        )
    except Exception as e:
        logger.exception("Failed to upsert repo: %s", e)
        _emit_phase(repo_id, "upload", status="error", message="Failed to create repo record")
        return

    _emit_phase(repo_id, "embedding", status="queued", progress=0)
    _emit_phase(repo_id, "indexing", status="queued", progress=0)
    _emit_phase(repo_id, "upload", status="running", progress=0, message="Starting Git clone", kind="github")

    try:
        def do_clone():
            normalized = ru.rstrip("/")
            if not normalized.lower().endswith(".git"):
                normalized += ".git"
            Repo.clone_from(
                normalized,
                dest,
                progress=GitCloneProgress(repo_id),
            )

        await asyncio.to_thread(do_clone)

        _emit_phase(repo_id, "upload", status="complete", progress=100, message="Git clone complete, starting indexing", kind="github")

        index_repo(dest, repo_id)

        await mark_repo_indexed(repo_id)

    except GitCommandError as e:
        logger.exception("Git clone failed: %s", e)
        _emit_phase(repo_id, "upload", status="error", message=f"Git clone failed: {e}")
    except Exception as e:
        logger.exception("Unexpected error during git clone: %s", e)
        _emit_phase(repo_id, "upload", status="error", message=str(e))



async def _process_zip_path(zip_path: str, *, repo_id: str, owner_user_id: Optional[str]) -> None:
    """
    Common ZIP processing: upsert repo (upload type), extract safely, index, mark indexed.
    Assumes the ZIP already exists at `zip_path`.
    """
    dest = os.path.join(UPLOAD_DIR, repo_id)
    os.makedirs(dest, exist_ok=True)

    filename = os.path.basename(zip_path)
    if not filename.lower().endswith(".zip"):
        _emit_phase(repo_id, "upload", status="error", message="Only .zip files are supported")
        return

    try:
        await upsert_repo(
            repo_id=repo_id,
            owner_user_id=owner_user_id,
            source_type="upload",
            source_uri=filename,
            storage_path=dest,
            title=None,
            is_shared=False,
        )
    except Exception as e:
        logger.exception("Failed to upsert repo: %s", e)
        _emit_phase(repo_id, "upload", status="error", message="Failed to create repo record")
        return

    _emit_phase(repo_id, "embedding", status="queued", progress=0)
    _emit_phase(repo_id, "indexing", status="queued", progress=0)

    _emit_phase(
        repo_id,
        "upload",
        status="running",
        progress=100,
        message="ZIP upload complete, extracting archive",
        kind="zip",
    )
    _emit_phase(repo_id, "upload", status="running", message="Extracting ZIP", kind="zip")

    dest_real = os.path.realpath(dest)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                extract_to = os.path.realpath(os.path.join(dest, info.filename))
                if not extract_to.startswith(dest_real + os.sep) and extract_to != dest_real:
                    raise ValueError(f"Unsafe path in ZIP: {info.filename}")
                z.extract(info, dest)
    except Exception as e:
        logger.exception("ZIP extraction failed: %s", e)
        _emit_phase(repo_id, "upload", status="error", message=f"ZIP extraction failed: {e}")
        return

    _emit_phase(
        repo_id,
        "upload",
        status="complete",
        progress=100,
        message="Extraction complete, starting indexing",
        kind="zip",
    )

    try:
        index_repo(dest, repo_id)
        await mark_repo_indexed(repo_id)
    except Exception as e:
        logger.exception("Indexing failed: %s", e)
        _emit_phase(repo_id, "indexing", status="error", message=str(e))
        return


async def handle_zip_upload(file: UploadFile, repo_id: str, *, owner_user_id: Optional[str] = None) -> None:
    """
    Receive and persist an uploaded ZIP during the request (NOT recommended for background tasks),
    then process it.
    """
    dest = os.path.join(UPLOAD_DIR, repo_id)
    os.makedirs(dest, exist_ok=True)

    filename = (file.filename or f"{repo_id}.zip").strip()
    if not filename.lower().endswith(".zip"):
        _emit_phase(repo_id, "upload", status="error", message="Only .zip files are supported")
        return

    zip_path = os.path.join(dest, filename)
    tmp_path = zip_path + ".part"

    bytes_total: Optional[int] = None
    try:
        hdr_val = file.headers.get("content-length") if hasattr(file, "headers") and file.headers else None
        if hdr_val:
            bytes_total = int(hdr_val)
    except Exception:
        bytes_total = None

    _emit_phase(
        repo_id,
        "upload",
        status="running",
        progress=0 if bytes_total else None,
        message="Starting ZIP upload",
        kind="zip",
        bytes_total=bytes_total,
        bytes_written=0,
    )

    written = 0
    chunk_size = 1024 * 1024
    try:
        async with aiofiles.open(tmp_path, "wb") as out_f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                await out_f.write(chunk)
                written += len(chunk)

                pct = None
                if bytes_total and bytes_total > 0:
                    pct = int(written * 100 / bytes_total)

                _emit_phase(
                    repo_id,
                    "upload",
                    status="running",
                    progress=pct,
                    message=f"Uploading ZIP ({written // 1024} KB)",
                    kind="zip",
                    bytes_total=bytes_total,
                    bytes_written=written,
                )

        try:
            os.replace(tmp_path, zip_path)
        except Exception:
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass
            os.rename(tmp_path, zip_path)

    except Exception as e:
        logger.exception("ZIP upload failed: %s", e)
        _emit_phase(repo_id, "upload", status="error", message=f"ZIP upload failed: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return

    await _process_zip_path(zip_path, repo_id=repo_id, owner_user_id=owner_user_id)


async def handle_zip_upload_from_path(zip_path: str, repo_id: str, *, owner_user_id: Optional[str] = None) -> None:
    """
    Background-task entrypoint: the route already wrote the ZIP to disk and passes its path.
    Just process the ZIP and clean up temp artifacts if any.
    """
    try:
        await _process_zip_path(zip_path, repo_id=repo_id, owner_user_id=owner_user_id)
    finally:
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass
        try:
            parent = os.path.dirname(zip_path)
            if parent and os.path.isdir(parent):
                os.rmdir(parent)
        except Exception:
            pass
