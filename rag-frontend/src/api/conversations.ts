// src/api/conversations.ts

import api from "./client";
import { Conversation, ChatMessage, HistoryRow } from "./types";

const normalizeConvo = (raw: any): Conversation | null => {
  const id =
    raw?.id ?? raw?.conversation_id ?? raw?.conversationId ?? raw?.pk ?? null;
  const repo_id = raw?.repo_id ?? raw?.repoId ?? raw?.repository_id ?? null;
  if (!id || !repo_id) return null;
  return {
    id: String(id),
    repo_id: String(repo_id),
    title:
      raw?.title ??
      raw?.name ??
      raw?.latest_question ??
      raw?.first_message?.content ??
      null,
    created_at: raw?.created_at ?? raw?.createdAt ?? null,
    updated_at: raw?.updated_at ?? raw?.updatedAt ?? null,
    latest_question: raw?.latest_question ?? null,
  };
};

export async function listConversations(): Promise<Conversation[]> {
  try {
    const res = await api.get<any[]>("/conversations");
    return (res.data || [])
      .map(normalizeConvo)
      .filter(Boolean) as Conversation[];
  } catch {
    const res = await api.get<any[]>("/conversations/");
    return (res.data || [])
      .map(normalizeConvo)
      .filter(Boolean) as Conversation[];
  }
}

export async function getConversation(
  conversationId: string
): Promise<Conversation | null> {
  const res = await api.get<any>(`/conversations/${conversationId}`);
  return normalizeConvo(res.data);
}

export async function createConversation(
  repoId: string
): Promise<Conversation | null> {
  const res = await api.post<any>("/conversations", { repo_id: repoId });
  return normalizeConvo(res.data?.conversation ?? res.data);
}

export async function deleteConversation(
  conversationId: string
): Promise<void> {
  await api.delete(`/conversations/${conversationId}`);
}

export async function listMessages(
  conversationId: string
): Promise<ChatMessage[]> {
  const res = await api.get<any[]>(`/messages`, {
    params: { conversation_id: conversationId },
  });
  const raw = res.data || [];
  return raw
    .map((m) => ({
      id: String(m.id),
      role: m.role,
      content: m.content,
      created_at: m.created_at ?? m.createdAt ?? null,
    }))
    .sort((a, b) => {
      const ta = a.created_at ? Date.parse(a.created_at) : 0;
      const tb = b.created_at ? Date.parse(b.created_at) : 0;
      return ta - tb;
    });
}

export async function createMessage(
  conversationId: string,
  role: "user" | "assistant",
  content: string
): Promise<ChatMessage | null> {
  const res = await api.post<any>("/messages", {
    conversation_id: conversationId,
    role,
    content,
  });
  const row = res.data;
  if (!row) return null;
  return {
    id: String(row.id),
    role: row.role,
    content: row.content,
    created_at: row.created_at ?? row.createdAt ?? new Date().toISOString(),
  };
}

export async function getContextsHistory(
  conversationId: string
): Promise<HistoryRow[]> {
  const res = await api.get<HistoryRow[]>(
    `/conversations/${encodeURIComponent(conversationId)}/contexts/history`
  );
  return res.data || [];
}
