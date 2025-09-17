// src/pages/ChatPage.tsx
// assisted with chatgpt5

import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import { Toaster, toast } from "sonner";
import { UploadForm } from "../components/UploadForm";
import { AnswerDisplay } from "../components/AnswerDisplay";
import { useAuth } from "../context/AuthContext";
import { useNavigate, useParams } from "react-router-dom";
import Sidebar, {
  Conversation as SidebarConversation,
} from "../components/Sidebar";
import { QueryForm } from "../components/QueryForm";
import { FileTree } from "../components/FileTree";

import { askAnswer } from "../api/answers";
import {
  listConversations,
  getConversation,
  createConversation,
  listMessages,
  createMessage,
  getContextsHistory,
} from "../api/conversations";
import { getRepoStatus, getRepoRawBlobUrl } from "../api/repos";

type ContextItem = {
  id?: string;
  filename?: string;
  content?: string;
  score?: number;
  file?: string;
  snippet?: string;
  metadata?: any;
};
interface ChatMessage {
  id: string;
  content: string;
  role: "user" | "assistant";
  created_at?: string | null;
  contexts?: ContextItem[];
}
type PhaseState = {
  status?: "queued" | "running" | "complete" | "error" | string;
  processed?: number;
  total?: number;
  message?: string;
  error?: string;
  startedAt?: number;
  finishedAt?: number;
};
type RepoStatus = {
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
type HistoryRow = {
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

const LS_REPO = "lastRepoId";
const LS_CONV = "lastConversationId";
const LS_RIGHT_OPEN = "chat:rightOpen";
const LS_RIGHT_W = "chat:rightWidth";

const ctxKey = (cid: string) => `ctxcache:${cid}`;
function readCtxCache(cid: string): Record<string, ContextItem[]> {
  try {
    const raw = localStorage.getItem(ctxKey(cid));
    if (!raw) return {};
    const obj = JSON.parse(raw);
    return typeof obj === "object" && obj ? obj : {};
  } catch {
    return {};
  }
}
function writeCtxCache(cid: string, map: Record<string, ContextItem[]>) {
  try {
    localStorage.setItem(ctxKey(cid), JSON.stringify(map));
  } catch {}
}
function mergeCtxCache(
  cid: string,
  add: Record<string, ContextItem[]>
): Record<string, ContextItem[]> {
  const base = readCtxCache(cid);
  const merged = { ...base, ...add };
  writeCtxCache(cid, merged);
  return merged;
}

const extOf = (p: string) => p.split(".").pop()?.toLowerCase() || "";
const isImageExt = (e: string) =>
  ["png", "jpg", "jpeg", "gif", "webp", "bmp", "avif"].includes(e);
const isSvgExt = (e: string) => e === "svg";
const isPdfExt = (e: string) => e === "pdf";

export default function ChatPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const params = useParams<{ id?: string }>();
  const routeConversationId = params.id || null;

  const [repoId, setRepoId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [isAsking, setIsAsking] = useState(false);

  const [allConvos, setAllConvos] = useState<SidebarConversation[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState("");

  const [repoStatus, setRepoStatus] = useState<RepoStatus | null>(null);
  const [manuallyReady, setManuallyReady] = useState(false);

  const lastRepoRef = useRef<string | null>(null);
  const restoreDoneRef = useRef(false);
  const [reloadKey, setReloadKey] = useState(0);

  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior });
    else if (scrollAreaRef.current) {
      const el = scrollAreaRef.current;
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  const [rightOpen, setRightOpen] = useState<boolean>(() => {
    const raw = localStorage.getItem(LS_RIGHT_OPEN);
    return raw ? raw === "1" : true;
  });
  const [rightWidth, setRightWidth] = useState<number>(() => {
    const raw = Number(localStorage.getItem(LS_RIGHT_W));
    return Number.isFinite(raw) && raw >= 280 ? raw : 380;
  });
  useEffect(() => {
    localStorage.setItem(LS_RIGHT_OPEN, rightOpen ? "1" : "0");
  }, [rightOpen]);
  useEffect(() => {
    localStorage.setItem(LS_RIGHT_W, String(rightWidth));
  }, [rightWidth]);

  const dragRef = useRef<{ startX: number; startW: number } | null>(null);
  const onDragStart = (e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startW: rightWidth };
    window.addEventListener("mousemove", onDragging);
    window.addEventListener("mouseup", onDragEnd);
  };
  const onDragging = (e: MouseEvent) => {
    if (!dragRef.current) return;
    const delta = dragRef.current.startX - e.clientX;
    const next = Math.min(640, Math.max(280, dragRef.current.startW + delta));
    setRightWidth(next);
  };
  const onDragEnd = () => {
    dragRef.current = null;
    window.removeEventListener("mousemove", onDragging);
    window.removeEventListener("mouseup", onDragEnd);
  };

  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<string>("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const handleSelectFile = useCallback((path: string, content: string) => {
    setPreviewPath(path);
    setPreviewContent(content);
  }, []);

  useEffect(() => {
    let currentUrl: string | null = null;
    let cancelled = false;

    async function load() {
      if (!repoId || !previewPath) {
        setPreviewUrl(null);
        return;
      }
      const ext = extOf(previewPath);
      if (!(isImageExt(ext) || isSvgExt(ext) || isPdfExt(ext))) {
        setPreviewUrl(null);
        return;
      }

      try {
        currentUrl = await getRepoRawBlobUrl(repoId, previewPath);
        if (!cancelled) setPreviewUrl(currentUrl);
      } catch (e) {
        console.warn("Preview load failed:", e);
        if (!cancelled) setPreviewUrl(null);
      }
    }

    void load();

    return () => {
      cancelled = true;
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [repoId, previewPath]);

  useEffect(() => {
    setConversationId(routeConversationId);
    if (routeConversationId) setNewRepoMode(false);
  }, [routeConversationId]);
  const [newRepoMode, setNewRepoMode] = useState(false);

  useEffect(() => {
    if (!routeConversationId) return;
    (async () => {
      try {
        const conv = await getConversation(routeConversationId);
        if (conv) {
          setRepoId(conv.repo_id);
          localStorage.setItem(LS_REPO, conv.repo_id);
          localStorage.setItem(LS_CONV, conv.id);
          setExpanded((p) => ({ ...p, [conv.repo_id]: true }));
        }
      } catch {}
    })();
  }, [routeConversationId]);

  useEffect(() => {
    if (restoreDoneRef.current) return;
    restoreDoneRef.current = true;
    if (routeConversationId) return;
    const savedRepo = localStorage.getItem(LS_REPO);
    const savedConv = localStorage.getItem(LS_CONV);
    if (savedRepo) setRepoId(savedRepo);
    if (savedConv) setConversationId(savedConv);
  }, [routeConversationId]);

  useEffect(() => {
    if (repoId) localStorage.setItem(LS_REPO, repoId);
  }, [repoId]);
  useEffect(() => {
    if (conversationId) localStorage.setItem(LS_CONV, conversationId);
  }, [conversationId]);

  const fetchAllConversations = useCallback(async () => {
    try {
      const list = await listConversations();
      setAllConvos(list as SidebarConversation[]);
      if (!routeConversationId && !conversationId && list[0]) {
        setRepoId(list[0].repo_id);
        setConversationId(list[0].id);
      }
    } catch {
      setAllConvos([]);
    }
  }, [conversationId, routeConversationId]);

  useEffect(() => {
    void fetchAllConversations();
  }, [fetchAllConversations, reloadKey]);

  const convosByRepo = useMemo(() => {
    const map: Record<string, SidebarConversation[]> = {};
    for (const c of allConvos) (map[c.repo_id] = map[c.repo_id] || []).push(c);
    for (const rid of Object.keys(map)) {
      map[rid].sort((a, b) => {
        const at = Date.parse(b.updated_at || b.created_at || "") || 0;
        const bt = Date.parse(a.updated_at || a.created_at || "") || 0;
        return at - bt;
      });
    }
    return map;
  }, [allConvos]);

  const filteredConvosByRepo = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return convosByRepo;
    const out: Record<string, SidebarConversation[]> = {};
    for (const [rid, list] of Object.entries(convosByRepo)) {
      const repoLabel = rid;
      const convs = list.filter((c) => {
        const t =
          c.title || c.latest_question || `Conversation ${c.id.slice(0, 8)}`;
        return (
          repoLabel.toLowerCase().includes(term) ||
          t.toLowerCase().includes(term)
        );
      });
      if (convs.length) out[rid] = convs;
    }
    return out;
  }, [search, convosByRepo]);

  const reqSeqRef = useRef(0);
  const [ctxHistory, setCtxHistory] = useState<HistoryRow[]>([]);
  const [ctxByMessage, setCtxByMessage] = useState<
    Record<string, ContextItem[]>
  >({});

  useEffect(() => {
    if (!conversationId) {
      setChatHistory([]);
      setCtxHistory([]);
      setCtxByMessage({});
      return;
    }

    const seq = ++reqSeqRef.current;
    const ctrl = new AbortController();

    (async () => {
      try {
        const msgs = await listMessages(conversationId);

        const cached = readCtxCache(conversationId);
        const withCache = msgs.map((m) =>
          (m as any).role === "assistant" && cached[m.id]?.length
            ? { ...(m as any), contexts: cached[m.id] }
            : (m as any)
        ) as ChatMessage[];

        if (seq === reqSeqRef.current && !ctrl.signal.aborted) {
          setChatHistory(withCache);
          requestAnimationFrame(() => scrollToBottom("auto"));
        }

        let history: HistoryRow[] = [];
        try {
          history = await getContextsHistory(conversationId);
        } catch {}

        const byMessage: Record<string, ContextItem[]> = {};
        const leftovers: HistoryRow[] = [];
        for (const row of history) {
          const items =
            (row?.contexts || []).map((c) => ({
              id: c.id,
              filename: c.filename,
              content: c.content,
              score: c.score ?? undefined,
            })) || [];
          if (row.message_id) byMessage[row.message_id] = items;
          else leftovers.push(row);
        }

        const toPersist: Record<string, ContextItem[]> = {};
        const merged = withCache.map((m) => {
          if (m.role !== "assistant") return m;
          const server = byMessage[m.id];
          if (server?.length) {
            toPersist[m.id] = server;
            return { ...m, contexts: server };
          }
          if (m.contexts?.length) {
            toPersist[m.id] = m.contexts;
            return m;
          }
          return m;
        });

        if (leftovers.length) {
          const idxs = merged
            .map((m, i) =>
              m.role === "assistant" && !m.contexts?.length ? i : -1
            )
            .filter((i) => i >= 0);
          const assign = Math.min(idxs.length, leftovers.length);
          for (let k = 0; k < assign; k++) {
            const i = idxs[idxs.length - 1 - k];
            const row = leftovers[k];
            const items =
              (row?.contexts || []).map((c) => ({
                id: c.id,
                filename: c.filename,
                content: c.content,
                score: c.score ?? undefined,
              })) || [];
            merged[i] = { ...merged[i], contexts: items };
            toPersist[merged[i].id] = items;
          }
        }

        const persisted = mergeCtxCache(conversationId, toPersist);
        if (seq === reqSeqRef.current && !ctrl.signal.aborted) {
          setChatHistory(merged);
          setCtxHistory(history);
          setCtxByMessage(persisted);
        }
      } catch (e: any) {
        if (e?.name !== "AbortError")
          console.error("Load conversation error:", e);
      }
    })();

    return () => ctrl.abort();
  }, [conversationId, scrollToBottom]);

  const { usedCounts, usedSamples } = useMemo(() => {
    const counts: Record<string, number> = {};
    const samples: Record<string, string> = {};
    const push = (f: string | undefined, c: string | undefined) => {
      if (!f) return;
      counts[f] = (counts[f] || 0) + 1;
      if (c && !samples[f]) samples[f] = c.slice(0, 240);
    };
    Object.values(ctxByMessage || {}).forEach((arr) =>
      (arr || []).forEach((x) => push(x.filename, x.content))
    );
    (ctxHistory || []).forEach((row) =>
      (row.contexts || []).forEach((x) => push(x.filename, x.content))
    );
    return { usedCounts: counts, usedSamples: samples };
  }, [ctxByMessage, ctxHistory, conversationId]);

  useEffect(() => {
    setManuallyReady(false);
    setRepoStatus(null);
    if (!repoId) return;
    (async () => {
      try {
        const s = await getRepoStatus(repoId);
        if (!s) return;
        setRepoStatus(s);
        const label = (s.status || "").toLowerCase();
        const docs = Number(s.stats?.documents || 0);
        if (label === "indexed" || label === "done" || docs > 0) {
          setManuallyReady(true);
        }
      } catch {}
    })();
  }, [repoId]);

  const handleRepoId = useCallback(
    async (newRepoId: string) => {
      if (lastRepoRef.current !== newRepoId) {
        setChatHistory([]);
        lastRepoRef.current = newRepoId;
      }
      setRepoId(newRepoId);
      try {
        const conv = await createConversation(newRepoId);
        if (conv?.id) {
          setNewRepoMode(false);
          navigate(`/conversation/${conv.id}`, { replace: false });
        }
        setReloadKey((k) => k + 1);
        setExpanded((prev) => ({ ...prev, [newRepoId]: true }));
      } catch (e) {
        console.warn("Create conversation error:", e);
      }
    },
    [navigate]
  );

  const handleIndexed = useCallback(
    (id: string) => {
      toast.success("Repository ready");
      if (!repoId) setRepoId(id);
      setRepoStatus({
        repoId: id,
        status: "indexed",
        phases: {},
        stats: { documents: 1 },
      });
      setManuallyReady(true);
      setReloadKey((k) => k + 1);
    },
    [repoId]
  );

  const ensureConversation = useCallback(
    async (rid: string) => {
      if (conversationId) return conversationId;
      const conv = await createConversation(rid);
      if (!conv?.id) throw new Error("create conversation failed");
      setNewRepoMode(false);
      navigate(`/conversation/${conv.id}`, { replace: false });
      setReloadKey((k) => k + 1);
      return conv.id;
    },
    [conversationId, navigate]
  );

  const hasAssistantHistory = useMemo(
    () => chatHistory.some((m) => m.role === "assistant"),
    [chatHistory]
  );

  const isRepoReady = useMemo(() => {
    const label = (repoStatus?.status || "").toLowerCase();
    const docs = Number(repoStatus?.stats?.documents || 0);
    return (
      manuallyReady ||
      hasAssistantHistory ||
      label === "indexed" ||
      label === "done" ||
      docs > 0
    );
  }, [repoStatus, manuallyReady, hasAssistantHistory]);

  const handleAsk = useCallback(
    async (question: string) => {
      if (!repoId || isAsking) return;

      if (!isRepoReady) {
        try {
          const s = await getRepoStatus(repoId);
          if (s) {
            setRepoStatus(s);
            const label = (s.status || "").toLowerCase();
            const docs = Number(s.stats?.documents || 0);
            if (!(label === "indexed" || label === "done" || docs > 0)) {
              toast.error("Repository is not indexed yet.");
              return;
            }
          } else {
            toast.error("Repository is not ready yet.");
            return;
          }
        } catch {
          toast.error("Repository is not ready yet.");
          return;
        }
      }

      setIsAsking(true);
      try {
        const convId = await ensureConversation(repoId);
        const clientQueryId =
          (window.crypto as any)?.randomUUID?.() ||
          `${Date.now()}-${Math.random().toString(36).slice(2)}`;

        const tempId = `temp-${Date.now()}`;
        const userMsg: ChatMessage = {
          id: tempId,
          role: "user",
          content: question,
          created_at: new Date().toISOString(),
        };
        setChatHistory((h) => [...h, userMsg]);
        requestAnimationFrame(() => scrollToBottom("smooth"));

        await createMessage(convId, "user", question);

        const { answer, contexts } = await askAnswer({
          repo_id: repoId,
          query: question,
          conversation_id: convId,
          user_id: user?.id ?? null,
          client_query_id: clientQueryId,
        });

        const savedA = await createMessage(convId, "assistant", answer);
        const assistantMsg: ChatMessage = {
          id: savedA?.id ?? `a-${Date.now()}`,
          role: "assistant",
          content: answer,
          created_at: savedA?.created_at ?? new Date().toISOString(),
          contexts: contexts ?? [],
        };

        setChatHistory((h) => [
          ...h.filter((m) => m.id !== tempId),
          userMsg,
          assistantMsg,
        ]);
        requestAnimationFrame(() => scrollToBottom("smooth"));

        if (assistantMsg.contexts?.length && convId) {
          const merged = mergeCtxCache(convId, {
            [assistantMsg.id]: assistantMsg.contexts,
          });
          setCtxByMessage(merged);
        }

        setManuallyReady(true);
        setRepoStatus(
          (prev) =>
            prev ?? {
              repoId: repoId,
              status: "indexed",
              phases: {},
              stats: { documents: 1 },
            }
        );

        setReloadKey((k) => k + 1);
      } catch (e) {
        console.error("Ask error:", e);
      } finally {
        setIsAsking(false);
      }
    },
    [
      repoId,
      isAsking,
      isRepoReady,
      ensureConversation,
      user?.id,
      scrollToBottom,
    ]
  );

  const onToggleRepo = (rid: string) =>
    setExpanded((prev) => ({ ...prev, [rid]: !prev[rid] }));
  const onSelectConvo = (_rid: string, cid: string) => {
    setNewRepoMode(false);
    navigate(`/conversation/${cid}`);
  };
  const onSelectRepo = (rid: string) => {
    setNewRepoMode(false);
    setRepoId(rid);
  };
  const onNewRepo = () => {
    setNewRepoMode(true);
    setRepoId(null);
    setConversationId(null);
    setChatHistory([]);
    setRepoStatus(null);
    setManuallyReady(false);
    setCtxHistory([]);
    setCtxByMessage({});
    setPreviewPath(null);
    setPreviewContent("");
    setPreviewUrl(null);
  };

  const showUploadForm = useMemo(() => {
    if (newRepoMode) return true;
    if (!repoId) return true;
    if (conversationId || (chatHistory && chatHistory.length > 0)) return false;
    const label = (repoStatus?.status || "").toLowerCase();
    const docs = Number(repoStatus?.stats?.documents || 0);
    const terminal =
      label === "indexed" || label === "done" || label === "error" || docs > 0;
    return !terminal;
  }, [newRepoMode, repoId, conversationId, chatHistory, repoStatus]);

  const showIndexingNotice = useMemo(() => {
    if (!repoStatus) return false;
    const label = (repoStatus.status || "").toLowerCase();
    const docs = Number(repoStatus.stats?.documents || 0);
    if (docs > 0) return false;
    return (label === "indexing" || label === "upload") && !isAsking;
  }, [repoStatus, isAsking]);

  const activeConversationId = conversationId;

  const onNewChatForRepo = useCallback(
    async (rid: string) => {
      setNewRepoMode(false);
      try {
        const conv = await createConversation(rid);
        if (!conv?.id) {
          toast.error("Failed to create conversation");
          return;
        }
        setExpanded((p) => ({ ...p, [rid]: true }));
        setReloadKey((k) => k + 1);
        navigate(`/conversation/${conv.id}`, { replace: false });
      } catch {
        toast.error("Failed to create conversation");
      }
    },
    [navigate]
  );

  return (
    <>
      <Toaster position="top-right" richColors />

      {(() => {
        const handleWidth = rightOpen ? 6 : 0; // px
        const paneWidth = rightOpen ? rightWidth : 0; // px
        return (
          <div
            className="h-screen w-full grid"
            style={{
              gridTemplateColumns: `300px minmax(0,1fr) ${handleWidth}px ${paneWidth}px`,
            }}
          >
            <Sidebar
              convosByRepo={
                filteredConvosByRepo as Record<string, SidebarConversation[]>
              }
              expanded={expanded}
              search={search}
              activeConversationId={activeConversationId}
              onSearchChange={setSearch}
              onToggleRepo={onToggleRepo}
              onSelectConvo={onSelectConvo}
              onNewChat={onNewChatForRepo}
              onNewRepo={onNewRepo}
              onSelectRepo={onSelectRepo}
            />

            <main className="h-screen min-h-0 min-w-0 flex flex-col border-r border-gray-200 dark:border-gray-800">
              <div className="max-w-3xl w-full mx-auto flex-1 min-h-0 min-w-0 flex flex-col">
                <div className="px-4 pt-4 flex items-center gap-3">
                  {showUploadForm && (
                    <UploadForm
                      onRepoId={handleRepoId}
                      onIndexingComplete={handleIndexed}
                    />
                  )}

                  {repoId && (
                    <button
                      className="ml-auto text-xs rounded border px-3 py-1.5 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      onClick={() => setRightOpen((v) => !v)}
                      title={rightOpen ? "Hide files" : "Show files"}
                    >
                      {rightOpen ? "Hide files" : "Show files"}
                    </button>
                  )}
                </div>

                <div
                  ref={scrollAreaRef}
                  className="flex-1 min-h-0 overflow-y-auto px-4 pb-24 mt-4"
                >
                  {repoId && !newRepoMode && (
                    <div className="space-y-3">
                      {chatHistory.map((msg) => (
                        <div
                          key={msg.id}
                          className={`border rounded p-4 ${
                            msg.role === "user"
                              ? "bg-gray-50 dark:bg-gray-900/40"
                              : ""
                          }`}
                        >
                          {msg.role === "user" ? (
                            <p className="font-medium whitespace-pre-wrap">
                              {msg.content}
                            </p>
                          ) : (
                            <AnswerDisplay
                              answer={msg.content}
                              contexts={msg.contexts}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <div ref={bottomRef} className="h-0" />
                </div>

                {repoId && !newRepoMode && (
                  <div className="sticky bottom-0 w-full border-t bg-white/80 dark:bg-zinc-900/80 backdrop-blur supports-[backdrop-filter]:bg-white/60 px-4 py-3">
                    <div className="max-w-3xl mx-auto">
                      <QueryForm
                        key={conversationId || repoId}
                        repoId={repoId}
                        onAsk={async (q) => await handleAsk(q)}
                        onAnswer={() => {}}
                        onSelectFile={() => {}}
                        mode="composer"
                        disabled={!isRepoReady}
                      />
                      {showIndexingNotice && (
                        <p className="text-xs text-gray-500 mt-1">
                          Indexing… You can browse or upload another repo while
                          this finishes.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </main>

            <div
              onMouseDown={onDragStart}
              className="h-screen cursor-col-resize bg-transparent hover:bg-blue-300/40"
              style={{
                display: rightOpen ? "block" : "none",
                width: "100%",
              }}
              role="separator"
              aria-orientation="vertical"
            />

            <aside
              className={`h-screen min-h-0 min-w-0 overflow-hidden border-l border-gray-200 dark:border-gray-800 bg-white dark:bg-zinc-900 ${
                rightOpen ? "opacity-100" : "opacity-0 pointer-events-none"
              }`}
            >
              <div className="h-full grid grid-rows-[auto_minmax(0,1fr)]">
                {repoId ? (
                  <div className="p-3 border-b dark:border-gray-800">
                    <FileTree
                      repoId={repoId}
                      onSelectFile={handleSelectFile}
                      usedCounts={usedCounts}
                      usedSamples={usedSamples}
                      defaultFilter="all"
                    />
                  </div>
                ) : (
                  <div className="p-3 text-sm text-gray-500">
                    No repo selected
                  </div>
                )}

                <div className="min-h-0 overflow-auto">
                  {previewPath ? (
                    <div className="p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-sm font-medium truncate">
                          {previewPath}
                        </div>
                        <div className="flex gap-2">
                          {previewUrl && (
                            <a
                              href={previewUrl}
                              download
                              className="text-xs rounded border px-2 py-1 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                            >
                              Download
                            </a>
                          )}
                          <button
                            className="text-xs rounded border px-2 py-1 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                            onClick={() => {
                              if (previewContent) {
                                navigator.clipboard.writeText(previewContent);
                                toast.success("File copied");
                              } else {
                                toast.error("Nothing to copy");
                              }
                            }}
                          >
                            Copy file
                          </button>
                          <button
                            className="text-xs rounded border px-2 py-1 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                            onClick={() => {
                              setPreviewPath(null);
                              setPreviewContent("");
                              setPreviewUrl(null);
                            }}
                          >
                            Close
                          </button>
                        </div>
                      </div>

                      {(() => {
                        const ext = extOf(previewPath);
                        if (isPdfExt(ext) && previewUrl) {
                          return (
                            <iframe
                              title="pdf"
                              src={previewUrl}
                              className="w-full h-[calc(100vh-230px)] border rounded"
                            />
                          );
                        }
                        if ((isImageExt(ext) || isSvgExt(ext)) && previewUrl) {
                          return (
                            <div className="flex items-start justify-center">
                              <img
                                src={previewUrl}
                                alt={previewPath}
                                className="max-h-[calc(100vh-230px)] object-contain border rounded"
                              />
                            </div>
                          );
                        }
                        return (
                          <pre className="text-xs whitespace-pre-wrap break-words bg-gray-50 dark:bg-zinc-900 border rounded p-3 max-h-[calc(100vh-230px)] overflow-auto">
                            {previewContent}
                          </pre>
                        );
                      })()}
                    </div>
                  ) : (
                    <div className="h-full grid place-items-center text-xs text-gray-500">
                      Select a file to preview
                    </div>
                  )}
                </div>
              </div>
            </aside>
          </div>
        );
      })()}
    </>
  );
}
