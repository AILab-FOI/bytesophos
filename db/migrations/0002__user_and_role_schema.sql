/* assisted with chatgpt5 */
/* modified to simplify for my use case */
CREATE TABLE IF NOT EXISTS users(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text UNIQUE NOT NULL,
  name text,
  display_name text,
  password_hash text,
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS repos(
  id text PRIMARY KEY,
  owner_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  source_type text NOT NULL CHECK (source_type IN ('git', 'upload')),
  source_uri text,
  storage_path text NOT NULL,
  name text NOT NULL,
  title text,
  is_shared boolean NOT NULL DEFAULT FALSE,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_indexed_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_repos_owner_name ON repos(owner_user_id, name);

CREATE INDEX IF NOT EXISTS idx_repos_owner ON repos(owner_user_id);

CREATE INDEX IF NOT EXISTS idx_repos_created ON repos(created_at);

CREATE OR REPLACE FUNCTION derive_repo_name(_source_uri text, _storage_path text, _fallback text)
  RETURNS text
  AS $$
DECLARE
  s text := coalesce(nullif(btrim(_source_uri), ''), '');
  p text := coalesce(nullif(btrim(_storage_path), ''), '');
  base text;
BEGIN
  IF s ~* 'github\.com' THEN
    base := regexp_replace(s, '.*[/:]([^/]+?)(?:\.git)?/?$', '\1');
    RETURN lower(base);
  END IF;
  IF p <> '' THEN
    base := regexp_replace(p, '.*/', '');
    base := regexp_replace(base, '\.(zip|tar|tgz|tar\.gz|tar\.bz2)$', '', 'i');
    IF base <> '' THEN
      RETURN lower(base);
    END IF;
  END IF;
  RETURN lower(coalesce(nullif(btrim(_fallback), ''), 'repo'));
END;
$$
LANGUAGE plpgsql
IMMUTABLE;

CREATE OR REPLACE FUNCTION repos_before_ins_upd_fill_name()
  RETURNS TRIGGER
  AS $$
BEGIN
  IF NEW.name IS NULL OR btrim(NEW.name) = '' THEN
    NEW.name := derive_repo_name(NEW.source_uri, NEW.storage_path, NEW.id);
  END IF;
  RETURN NEW;
END;
$$
LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_repos_fill_name ON repos;

CREATE TRIGGER trg_repos_fill_name
  BEFORE INSERT OR UPDATE OF source_uri,
  storage_path,
  name,
  id ON repos
  FOR EACH ROW
  EXECUTE FUNCTION repos_before_ins_upd_fill_name();

CREATE TABLE IF NOT EXISTS conversations(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id text NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  title text,
  type text DEFAULT 'chat',
  source text,
  is_archived boolean NOT NULL DEFAULT FALSE,
  is_favorite boolean NOT NULL DEFAULT FALSE,
  last_interacted_at timestamptz DEFAULT now(),
  message_count integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_repo_id ON conversations(repo_id);

CREATE TABLE IF NOT EXISTS messages(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid REFERENCES conversations(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  content text NOT NULL,
  role text CHECK (ROLE IN ('user', 'assistant', 'system')) NOT NULL DEFAULT 'user',
  created_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS documents(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id text NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  title text,
  description text,
  source_type text,
  source_uri text,
  version integer NOT NULL DEFAULT 1,
  checksum text,
  ingestion_status text NOT NULL DEFAULT 'pending',
  ingested_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_documents_repo_id ON documents(repo_id);

CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);

CREATE OR REPLACE FUNCTION trg_sync_documents_repo_meta_fn()
  RETURNS TRIGGER
  AS $$
BEGIN
  NEW.metadata := jsonb_set(COALESCE(NEW.metadata, '{}'::jsonb), '{repo_id}', to_jsonb(NEW.repo_id), TRUE);
  RETURN NEW;
END;
$$
LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_documents_repo_meta ON documents;

CREATE TRIGGER trg_sync_documents_repo_meta
  BEFORE INSERT OR UPDATE OF repo_id ON documents
  FOR EACH ROW
  EXECUTE FUNCTION trg_sync_documents_repo_meta_fn();

CREATE TABLE IF NOT EXISTS document_chunks(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
  chunk_text text NOT NULL,
  chunk_hash text NOT NULL,
  chunk_index integer NOT NULL,
  start_offset integer,
  end_offset integer,
  search_vector tsvector,
  embedding vector(1536),
  embedding_model text,
  embedding_created_at timestamptz,
  embedding_metadata jsonb NOT NULL DEFAULT '{}',
  token_count integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_search_vector ON document_chunks USING GIN(search_vector);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON document_chunks USING ivfflat(embedding vector_l2_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS rag_queries(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid REFERENCES conversations(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id),
  query_text text NOT NULL,
  response_text text,
  response_metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_queries_conversation_created ON rag_queries(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS retrieved_chunks(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rag_query_id uuid REFERENCES rag_queries(id) ON DELETE CASCADE,
  document_chunk_id uuid REFERENCES document_chunks(id),
  score double precision,
  rank integer,
  used_in_prompt boolean NOT NULL DEFAULT TRUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_retrieved_chunks_rag_query_id ON retrieved_chunks(rag_query_id);

CREATE INDEX IF NOT EXISTS idx_retrieved_chunks_used ON retrieved_chunks(rag_query_id, used_in_prompt);

