# app/services/progress.py

"""Progress reporting utilities.

This module defines an abstract :class:`ProgressBroker` interface and an
in-memory implementation for tracking and streaming task progress for a
repository (e.g., upload → embedding → indexing). State is kept per
``repo_id`` and can be retrieved as a snapshot or streamed to subscribers.

Phases:
    - ``upload`` (optional)
    - ``embedding``
    - ``indexing``

Overall status synthesis:
    The in-memory broker derives a top-level status based on per-phase states,
    returning one of: ``"indexed"``, ``"indexing"``, ``"upload"``, ``"error"``,
    or ``"unknown"``.
"""
import asyncio
import json
import os
import time
from typing import Any, AsyncIterator, Dict, Optional

class ProgressBroker:
    """Interface for progress tracking and streaming."""

    async def update(
        self,
        repo_id: str,
        phase: str,
        status: str,
        processed: Optional[int] = None,
        total: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a progress update for a given repository and phase.

        Args:
            repo_id: Repository identifier whose progress is being updated.
            phase: Phase name (e.g., ``"upload"``, ``"embedding"``, ``"indexing"``).
            status: Phase status (e.g., ``"queued"``, ``"running"``,
                ``"complete"``, ``"error"``).
            processed: Number of items processed so far.
            total: Total number of items to process (if known).
            message: Optional human-readable message to attach.
            error: Optional error message when ``status == "error"``.

        Returns:
            dict: The current snapshot for ``repo_id`` *after* applying this update.

        Raises:
            NotImplementedError: Always, in the abstract base.
        """
        raise NotImplementedError

    async def snapshot(self, repo_id: str) -> Dict[str, Any]:
        """Return the current progress snapshot for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            dict: A JSON-serializable snapshot with overall status and per-phase
            details.
        """
        raise NotImplementedError

    async def subscribe(self, repo_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to progress updates for a repository.

        Starts by yielding the current snapshot, then yields incremental updates
        as they occur.

        Args:
            repo_id: Repository identifier to subscribe to.

        Yields:
            dict: A JSON-serializable payload representing either the initial
            snapshot or a subsequent update event.
        """
        raise NotImplementedError


class InMemoryProgressBroker(ProgressBroker):
    """In-memory :class:`ProgressBroker` implementation.

    Stores per-repo snapshots in-memory and fans out updates to per-repo queues
    for subscribers. This is suitable for a single-process deployment.
    """
    def __init__(self) -> None:
        """Initialize the broker with empty state and a process-local lock."""
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        self._subs: Dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    def _mk_base(self, repo_id: str) -> Dict[str, Any]:
        """Create a minimal snapshot structure for a new repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            dict: Base snapshot of the form ``{"repoId": repo_id, "phases": {}}``.
        """
        return {"repoId": repo_id, "phases": {}}

    def _overall(self, phases: Dict[str, Any]) -> Dict[str, Any]:
        """Derive the overall status from per-phase progress.

        The logic prioritizes later phases and errors. If indexing is complete,
        the overall status is ``"indexed"``; otherwise, it reflects the most
        advanced phase currently running or errored.

        Args:
            phases: Mapping of phase name to its status dictionary.

        Returns:
            dict: Overall status payload with keys ``"status"``, ``"processed"``,
            and ``"total"``.
        """
        def pct(p, t): return int(p * 100 / t) if (isinstance(p, int) and isinstance(t, int) and t > 0) else None
        up = phases.get("upload") or {}
        emb = phases.get("embedding") or {}
        idx = phases.get("indexing") or {}

        if (idx.get("status") == "complete"):
            return {"status": "indexed", "processed": idx.get("processed", 0), "total": idx.get("total", 0)}

        if idx.get("status") in ("running", "queued", "error"):
            st = "indexing" if idx.get("status") != "error" else "error"
            return {"status": st, "processed": idx.get("processed", 0), "total": idx.get("total", 0)}

        if emb.get("status") in ("running", "queued", "complete", "error"):
            st = "indexing" if emb.get("status") != "error" else "error"
            return {"status": st, "processed": emb.get("processed", 0), "total": emb.get("total", 0)}

        if up.get("status") in ("running", "queued"):
            return {"status": "upload", "processed": 0, "total": 0}
        if up.get("status") == "error":
            return {"status": "error", "processed": 0, "total": 0}
        return {"status": "unknown", "processed": 0, "total": 0}

    async def update(self, repo_id: str, phase: str, status: str,
                     processed: Optional[int]=None, total: Optional[int]=None,
                     message: Optional[str]=None, error: Optional[str]=None) -> Dict[str, Any]:
        """Record and broadcast a per-phase progress update.

        Also recalculates the overall snapshot and pushes an event to all
        subscribers for the given ``repo_id``.

        Args:
            repo_id: Repository identifier.
            phase: Phase name (e.g., ``"upload"``, ``"embedding"``, ``"indexing"``).
            status: Phase status (``"queued"``, ``"running"``, ``"complete"``,
                or ``"error"``).
            processed: Number of items processed so far for the phase.
            total: Total number of items for the phase, if known.
            message: Optional informational message for clients.
            error: Optional error message for clients when status is ``"error"``.

        Returns:
            dict: The updated snapshot for ``repo_id``.
        """
        async with self._lock:
            snap = self._snapshots.setdefault(repo_id, self._mk_base(repo_id))
            phases = snap.setdefault("phases", {})
            cur = phases.get(phase, {"status": "queued", "processed": 0, "total": None, "startedAt": time.time()})
            cur["status"] = status
            if processed is not None: cur["processed"] = processed
            if total is not None: cur["total"] = total
            if message is not None: cur["message"] = message
            if error is not None: cur["error"] = error
            if status in ("complete", "error"): cur["finishedAt"] = time.time()
            p = cur.get("processed"); t = cur.get("total")
            if isinstance(p, int) and isinstance(t, int) and t > 0:
                cur["progress"] = max(0, min(100, int(p * 100 / t)))
            phases[phase] = cur

            snap.update(self._overall(phases))

            payload = {
                "type": "task_update",
                "repoId": repo_id,
                "phase": phase,
                "status": status,
                "processed": cur.get("processed"),
                "total": cur.get("total"),
                "progress": cur.get("progress"),
                "message": message,
                "error": error,
                "event": "progress" if status == "running" else status,
            }
            for q in self._subs.get(repo_id, set()):
                try: q.put_nowait(payload)
                except: pass
            return snap

    async def snapshot(self, repo_id: str) -> Dict[str, Any]:
        """Return a copied snapshot for ``repo_id``.

        The snapshot is round-tripped through JSON to ensure it is
        JSON-serializable and detached from internal references.

        Args:
            repo_id: Repository identifier.

        Returns:
            dict: Current snapshot for the repository.
        """
        async with self._lock:
            return json.loads(json.dumps(self._snapshots.get(repo_id) or self._mk_base(repo_id)))

    async def subscribe(self, repo_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Yield the current snapshot, then stream subsequent updates.

        This creates a per-subscriber queue and cleans it up on exit.

        Args:
            repo_id: Repository identifier to observe.

        Yields:
            dict: Initial snapshot, followed by incremental update payloads.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subs.setdefault(repo_id, set()).add(q)
            yield await self.snapshot(repo_id)
        try:
            while True:
                yield await q.get()
        finally:
            async with self._lock:
                self._subs.get(repo_id, set()).discard(q)

BROKER: ProgressBroker = InMemoryProgressBroker()
"""Process-local singleton :class:`ProgressBroker` used by the application."""