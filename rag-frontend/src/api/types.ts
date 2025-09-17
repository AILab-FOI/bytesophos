// src/api/types.ts

export type PhaseState = {
  status?: "queued" | "running" | "complete" | "error" | string;
  processed?: number;
  total?: number;
  message?: string;
  error?: string;
  startedAt?: number;
  finishedAt?: number;
};

export type RepoStatus = {
  repoId: string;
  status:
    | "new"
    | "upload"
    | "indexing"
    | "indexed"
    | "done"
    | "error"
    | "missing"
    | string;
  phases: Record<string, PhaseState>;
  stats?: { documents?: number; [k: string]: any };
};

export type Conversation = {
  id: string;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  repo_id: string;
  latest_question?: string | null;
};

export type ChatMessage = {
  id: string;
  content: string;
  role: "user" | "assistant";
  created_at?: string | null;
};

export type ContextItem = {
  id?: string;
  filename?: string;
  content?: string;
  score?: number;
  file?: string;
  snippet?: string;
  metadata?: any;
};

export type HistoryRow = {
  message_id: string | null;
  rag_query_id: string;
  created_at?: string | null;
  contexts: Array<{
    id: string;
    filename: string;
    content: string;
    rank?: number | null;
    score?: number | null;
  }>;
};
