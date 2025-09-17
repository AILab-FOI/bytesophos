# app/db.py

import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_DSN")
pool: psycopg.AsyncConnection | None = None

async def connect_db():
    """Establish a connection to the PostgreSQL database.

    This function initializes a global asynchronous connection (`pool`)
    using the `DATABASE_DSN` environment variable.  
    If the connection already exists, it does nothing.

    Raises:
        RuntimeError: If the `DATABASE_DSN` environment variable is not set.
        psycopg.OperationalError: If the database connection fails.
    """
    global pool
    if pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_DSN is not set")
        pool = await psycopg.AsyncConnection.connect(
            DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        )


async def disconnect_db():
    """Close the active PostgreSQL connection.

    If no connection exists, this function does nothing.
    """
    global pool
    if pool:
        await pool.close()
        pool = None


async def init_pool():
    """Initialize the global database connection pool.

    This is a convenience wrapper around `connect_db`.
    It ensures that a database connection is ready to use.

    Raises:
        RuntimeError: If `DATABASE_DSN` is not set.
        psycopg.OperationalError: If the database connection fails.
    """
    await connect_db()


async def close_pool():
    """Close the global database connection pool.

    This is a convenience wrapper around `disconnect_db`.
    It ensures that the database connection is cleanly closed.
    """
    await disconnect_db()


async def fetch_all(query: str, params=None):
    """Fetch all rows matching the given SQL query.

    Args:
        query (str): SQL query to execute.
        params (dict | None): Query parameters to bind. Defaults to an empty dict.

    Returns:
        list[dict]: A list of rows, where each row is a dictionary
        mapping column names to their values.

    Raises:
        psycopg.DatabaseError: If the query execution fails.
    """
    if pool is None:
        await connect_db()
    async with pool.cursor() as cur:
        await cur.execute(query, params or {})
        return await cur.fetchall()


async def fetch_one(query: str, params=None):
    """Fetch a single row matching the given SQL query.

    Args:
        query (str): SQL query to execute.
        params (dict | None): Query parameters to bind. Defaults to an empty dict.

    Returns:
        dict | None: A dictionary representing a single row, or
        `None` if no matching row is found.

    Raises:
        psycopg.DatabaseError: If the query execution fails.
    """
    if pool is None:
        await connect_db()
    async with pool.cursor() as cur:
        await cur.execute(query, params or {})
        return await cur.fetchone()


async def execute(query: str, params=None):
    """Execute a SQL statement without returning rows.

    Useful for `INSERT`, `UPDATE`, or `DELETE` statements.

    Args:
        query (str): SQL statement to execute.
        params (dict | None): Query parameters to bind. Defaults to an empty dict.

    Raises:
        psycopg.DatabaseError: If the statement execution fails.
    """
    if pool is None:
        await connect_db()
    async with pool.cursor() as cur:
        await cur.execute(query, params or {})