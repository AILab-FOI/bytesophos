// src/api/ws.ts

export function buildProgressWsUrl(token: string, repoId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  const qs = new URLSearchParams({
    token,
    repo_id: repoId,
  }).toString();
  return `${proto}://${host}/api/ws/progress?${qs}`;
}
