# app/config.py

"""
Application configuration settings.

Centralised configuration using Pydantic v2 (pydantic-settings). All values
are validated and available both through the `settings` object and as
module-level constants for convenient imports.
"""

from __future__ import annotations

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyHttpUrl
from pydantic import model_validator


class Settings(BaseSettings):
    DATABASE_DSN: Optional[str] = Field(
        default="postgresql://bytesophos_user:Test1234!@rag_postgres:5432/bytesophos",
        description="PostgreSQL DSN, e.g. postgresql+psycopg://user:pass@host:5432/db",
    )
    PG_CONN_STR: Optional[str] = Field(
        default="postgresql://bytesophos_user:Test1234!@rag_postgres:5432/bytesophos", alias="pg_conn_str",
        description="Alternate DSN env var; used if DATABASE_DSN is missing.",
    )
    POSTGRES_USER: Optional[str] = Field(default=None, alias="postgres_user")
    POSTGRES_PASSWORD: Optional[str] = Field(default=None, alias="postgres_password")
    POSTGRES_HOST: str = Field("postgres", alias="postgres_host")
    POSTGRES_PORT: int = Field(5432, alias="postgres_port")
    POSTGRES_DB: Optional[str] = Field(default=None, alias="postgres_db")

    JWT_SECRET: str = Field(..., description="Secret key for signing JWTs.")
    JWT_ALGORITHM: str = Field("HS256", description="JWT signing algorithm.")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        60 * 24, description="Lifetime of access tokens (default: 1 day)."
    )
    TOKEN_EXPIRE_MINUTES: int = Field(
        60 * 24, description="Lifetime of generic tokens (default: 1 day)."
    )

    GROQ_API_KEY: str | None = Field(
        None, alias="groq_api_key", description="API key for the Groq LLM provider."
    )
    GROQ_API_BASE: AnyHttpUrl = Field(
        "https://api.groq.com/openai/v1", description="Base URL for the Groq API."
    )
    GROQ_MODEL: str = Field(
        "qwen/qwen3-32b", description="Groq model to use (default: qwen3-32b)."
    )

    OPENAI_API_KEY: str | None = Field(
        None, alias="openai_api_key", description="OpenAI API key (optional)."
    )
    VOYAGE_API_KEY: str | None = Field(
        None, alias="voyage_api_key", description="VoyageAI API key (optional)."
    )

    RETRIEVAL_MIN_SCORE: float = Field(
        0.55, alias="retrieval_min_score", description="Minimum score cutoff for retrieved chunks."
    )

    UPLOAD_DIR: str = Field("uploads", description="Directory for user-uploaded files.")
    DATA_DIR: str = Field(
        "data/repos", description="Directory for repository data and query history."
    )

    EMBEDDINGS_INDEX: str = Field(
        "embeddings", description="Haystack pgvector table name."
    )

    VOYAGE_EMBED_MODEL: str = Field(
        "voyage-code-2",
        env="VOYAGE_EMBED_MODEL",
        description="Voyage embedding model id (e.g., voyage-code-2, voyage-2-lite, etc.)",
    )

    VOYAGE_RERANK_MODEL: str = Field(
        "rerank-2.5-lite",
        env="VOYAGE_RERANK_MODEL",
        description="Voyage reranker model id (one of rerank-lite-1, rerank-2-lite, rerank-2, rerank-2.5, rerank-2.5-lite)",
    )
    

    MODEL_CONTEXT_TOKENS: int = Field(
        32_000,
        description=(
            "Maximum context window (in tokens) of the target LLM. "
            "qwen/qwen-3-32b is ~32k tokens."
        ),
    )
    TOKENS_PER_CHAR: float = Field(
        0.25,
        description=(
            "Approximate token-per-character ratio used to estimate history size. "
            "0.25 ≈ 4 characters per token."
        ),
    )
    HISTORY_BUDGET_FRACTION: float = Field(
        0.35,
        description=(
            "Fraction of the model context to allocate to conversation history. "
            "E.g. 0.35 = 35 % of the context window."
        ),
    )
    SAFETY_MARGIN_TOKENS: int = Field(
        1500,
        description=(
            "Tokens reserved for system instructions and the model's answer "
            "to avoid overfilling the prompt."
        ),
    )
    MAX_HISTORY_TOKENS: int | None = Field(
        None,
        description=(
            "Optional hard cap on total history tokens. "
            "Set to None to disable total-history truncation."
        ),
    )

    CHUNK_MAX_CHARS: int = Field(
        10_000, description="Max characters per chunk produced by the chunker."
    )
    CHUNK_OVERLAP: int = Field(
        200, description="Character overlap between adjacent chunks."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",        
        case_sensitive=False, 
        extra="ignore",      
    )


settings = Settings()

DATABASE_DSN = settings.DATABASE_DSN

JWT_SECRET = settings.JWT_SECRET
JWT_ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
TOKEN_EXPIRE_MINUTES = settings.TOKEN_EXPIRE_MINUTES

GROQ_API_KEY = settings.GROQ_API_KEY
GROQ_API_BASE = settings.GROQ_API_BASE
GROQ_MODEL = settings.GROQ_MODEL

OPENAI_API_KEY = settings.OPENAI_API_KEY
VOYAGE_API_KEY = settings.VOYAGE_API_KEY
RETRIEVAL_MIN_SCORE = settings.RETRIEVAL_MIN_SCORE

UPLOAD_DIR = settings.UPLOAD_DIR
DATA_DIR = settings.DATA_DIR

EMBEDDINGS_INDEX = settings.EMBEDDINGS_INDEX
VOYAGE_EMBED_MODEL = settings.VOYAGE_EMBED_MODEL
VOYAGE_RERANK_MODEL = settings.VOYAGE_RERANK_MODEL

MODEL_CONTEXT_TOKENS = settings.MODEL_CONTEXT_TOKENS
TOKENS_PER_CHAR = settings.TOKENS_PER_CHAR
HISTORY_BUDGET_FRACTION = settings.HISTORY_BUDGET_FRACTION
SAFETY_MARGIN_TOKENS = settings.SAFETY_MARGIN_TOKENS
MAX_HISTORY_TOKENS = settings.MAX_HISTORY_TOKENS

CHUNK_MAX_CHARS = settings.CHUNK_MAX_CHARS
CHUNK_OVERLAP = settings.CHUNK_OVERLAP