// src/api/uploads.ts

import api from "../api/client";

export type UploadProgress = (pct: number) => void;

export async function uploadGithubRepo(
  repoUrl: string,
  token?: string
): Promise<string> {
  const form = new FormData();
  form.append("type", "github");
  form.append("repo_url", repoUrl);

  const res = await api.post("/upload", form, {
    headers: {
      "Content-Type": "multipart/form-data",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  const id = res?.data?.repoId ?? res?.data?.repo_id;
  if (!id) throw new Error("Upload response missing repoId");
  return id as string;
}

export async function uploadZipRepo(
  file: File,
  token?: string,
  onProgress?: UploadProgress
): Promise<string> {
  const form = new FormData();
  form.append("type", "zip");
  form.append("file", file);

  const res = await api.post("/upload", form, {
    headers: {
      "Content-Type": "multipart/form-data",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    onUploadProgress: (e) => {
      if (!onProgress) return;
      const pct = Math.round((e.loaded * 100) / (e.total ?? e.loaded));
      onProgress(pct);
    },
  });

  const id = res?.data?.repoId ?? res?.data?.repo_id;
  if (!id) throw new Error("Upload response missing repoId");
  return id as string;
}
