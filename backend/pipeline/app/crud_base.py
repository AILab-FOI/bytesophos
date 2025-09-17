# app/crud_base.py

from __future__ import annotations
from typing import Any, Dict, Iterable, Optional, Sequence
from app.db import fetch_all, fetch_one, execute

class CRUDBase:
    """
    Minimal repository with parameterized queries.
    NOTE: table/id_column must come from trusted code, not user input.
    """

    def __init__(self, table: str, id_column: str = "id", allowed_columns: Optional[Iterable[str]] = None) -> None:
        self.table = table
        self.id_column = id_column
        self.allowed = set(allowed_columns or [])

    def _filter_allowed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.allowed:
            return data
        return {k: v for k, v in data.items() if k in self.allowed}

    async def list(self, filters: Optional[Dict[str, Any]] = None) -> Sequence[Dict[str, Any]]:
        base = f'SELECT * FROM "{self.table}"'
        params: Dict[str, Any] = {}
        if filters:
            where = " AND ".join(f'"{k}" = %({k})s' for k in filters)
            base += f" WHERE {where}"
            params.update(filters)
        return await fetch_all(base, params)

    async def get(self, item_id: Any) -> Dict[str, Any]:
        row = await fetch_one(
            f'SELECT * FROM "{self.table}" WHERE "{self.id_column}" = %(id)s LIMIT 1',
            {"id": item_id},
        )
        if not row:
            raise KeyError(f"{self.table} not found")
        return row

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict) or not data:
            raise ValueError("Empty payload")
        data = self._filter_allowed(data)
        if not data:
            raise ValueError("No allowed fields to insert")
        keys = list(data.keys())
        cols = ", ".join(f'"{k}"' for k in keys)
        vals = ", ".join(f"%({k})s" for k in keys)
        query = f'INSERT INTO "{self.table}" ({cols}) VALUES ({vals}) RETURNING *'
        return await fetch_one(query, data)

    async def update(self, item_id: Any, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict) or not data:
            raise ValueError("No fields to update")
        data = self._filter_allowed(data)
        if not data:
            raise ValueError("No allowed fields to update")
        set_clause = ", ".join(f'"{k}" = %({k})s' for k in data.keys())
        params = {**data, "id": item_id}
        row = await fetch_one(
            f'UPDATE "{self.table}" SET {set_clause} WHERE "{self.id_column}" = %(id)s RETURNING *',
            params,
        )
        if not row:
            raise KeyError(f"{self.table} not found")
        return row

    async def delete(self, item_id: Any) -> Dict[str, str]:
        await execute(f'DELETE FROM "{self.table}" WHERE "{self.id_column}" = %(id)s', {"id": item_id})
        return {"status": "deleted"}