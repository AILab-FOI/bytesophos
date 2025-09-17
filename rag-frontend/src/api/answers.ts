// src/api/answers.ts

import api from "./client";
import { ContextItem } from "./types";

export async function askAnswer(params: {
  repo_id: string;
  query: string;
  conversation_id?: string | null;
  user_id?: string | null;
  client_query_id?: string | null;
}): Promise<{ answer: string; contexts?: ContextItem[] }> {
  const res = await api.post<{ answer: string; contexts?: ContextItem[] }>(
    "/repos/answer",
    params
  );
  return res.data;
}
