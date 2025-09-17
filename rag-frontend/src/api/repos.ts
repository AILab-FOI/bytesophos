// src/api/repos.ts

import api from "./client";
import { RepoStatus } from "./types";

export async function getRepoStatus(
  repoId: string
): Promise<RepoStatus | null> {
  const res = await api.get<RepoStatus>(
    `/repos/${encodeURIComponent(repoId)}/status`
  );
  return res.data ?? null;
}

export async function listRepoFiles(
  repoId: string,
  token?: string
): Promise<string[]> {
  const res = await api.get<string[]>(
    `/repos/${encodeURIComponent(repoId)}/files`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }
  );
  return res.data ?? [];
}

export async function getRepoFile(
  repoId: string,
  path: string,
  token?: string
): Promise<{ content: string }> {
  const res = await api.get<{ content: string }>(
    `/repos/${encodeURIComponent(repoId)}/file`,
    {
      params: { path },
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }
  );
  return res.data;
}

export async function getRepoNames(
  token?: string
): Promise<Record<string, string>> {
  const res = await api.get<Record<string, string>>("/repos/names", {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  return res.data || {};
}

export async function deleteRepo(
  repoId: string,
  token?: string
): Promise<boolean> {
  const res = await api.delete<{ status: string; repoId: string }>(
    `/repos/${encodeURIComponent(repoId)}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }
  );
  return res.data?.status === "deleted";
}

export type RepoBrief = {
  id: string;
  label: string;
  source_type?: "git" | "upload";
};

export async function getRepoBriefs(
  token?: string
): Promise<Record<string, RepoBrief>> {
  try {
    const res = await api.get<RepoBrief[]>("/repos/briefs", {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    const map: Record<string, RepoBrief> = {};
    for (const r of res.data || []) map[r.id] = r;
    return map;
  } catch (err: any) {
    if (err?.response?.status !== 404) throw err;
    const names = await getRepoNames(token);
    const map: Record<string, RepoBrief> = {};
    for (const [id, label] of Object.entries(names || {})) {
      map[id] = { id, label };
    }
    return map;
  }
}

export async function getRepoRawBlobUrl(
  repoId: string,
  path: string,
  token?: string
): Promise<string> {
  const res = await api.get(`/repos/${encodeURIComponent(repoId)}/raw`, {
    params: { path },
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    responseType: "blob",
  });
  const blob = res.data as Blob;
  return URL.createObjectURL(blob);
}
