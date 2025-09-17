// src/components/Sidebar.tsx

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Plus,
  Search,
  ChevronRight,
  ChevronDown,
  MessageSquare,
  Trash,
  Loader2,
  Github,
  FileArchive,
  MoreVertical,
} from "lucide-react";

import {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "./ui/alert-dialog";

import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";

import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "./ui/dropdown-menu";

import { toast } from "sonner";
import { deleteRepo, RepoBrief, getRepoBriefs } from "./../api/repos";

export type Conversation = {
  id: string;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  repo_id: string;
  latest_question?: string | null;
};

type SidebarProps = {
  convosByRepo: Record<string, Conversation[]>;
  expanded: Record<string, boolean>;
  search: string;
  activeConversationId?: string | null;

  onSearchChange: (v: string) => void;
  onToggleRepo: (repoId: string) => void;
  onSelectConvo: (repoId: string, convoId: string) => void;
  onNewChat: (repoId: string) => void;
  onNewRepo: () => void;
  onSelectRepo?: (repoId: string) => void;
  onDeleteConvo?: (repoId: string, convoId: string) => Promise<void> | void;
  onConvoDeleted?: (repoId: string, convoId: string) => void;
  onRepoDeleted?: (repoId: string) => void;
};

export default function Sidebar({
  convosByRepo,
  expanded,
  search,
  activeConversationId,
  onSearchChange,
  onToggleRepo,
  onSelectConvo,
  onNewChat,
  onNewRepo,
  onSelectRepo,
  onDeleteConvo,
  onConvoDeleted,
  onRepoDeleted,
}: SidebarProps) {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [repoDeletingId, setRepoDeletingId] = useState<string | null>(null);

  const [deleteRepoOpenId, setDeleteRepoOpenId] = useState<string | null>(null);

  const [hiddenRepoIds, setHiddenRepoIds] = useState<Set<string>>(new Set());

  const [hiddenDeletedIds, setHiddenDeletedIds] = useState<Set<string>>(
    new Set()
  );

  const [briefs, setBriefs] = useState<Record<string, RepoBrief>>({});
  const [namesLoaded, setNamesLoaded] = useState(false);

  const lastRepoIdsRef = useRef<Set<string>>(new Set());
  const fetchInFlightRef = useRef(false);

  const repoIds = useMemo(() => {
    const a = Object.keys(convosByRepo);
    const b = Object.keys(briefs);
    const union = Array.from(new Set([...a, ...b]));
    return union.filter((id) => !hiddenRepoIds.has(id));
  }, [convosByRepo, briefs, hiddenRepoIds]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        fetchInFlightRef.current = true;
        const map = await getRepoBriefs();
        if (!cancelled) {
          setBriefs(map);
          setNamesLoaded(true);
        }
      } catch (e) {
        if (!cancelled) setNamesLoaded(true);
        console.warn("Failed to fetch repo briefs:", e);
      } finally {
        fetchInFlightRef.current = false;
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const currentSet = new Set(repoIds);
    let needsRefresh = false;

    for (const id of currentSet) {
      if (!lastRepoIdsRef.current.has(id)) {
        needsRefresh = true;
        break;
      }
      if (!briefs[id]) {
        needsRefresh = true;
        break;
      }
    }

    lastRepoIdsRef.current = currentSet;

    if (!needsRefresh || fetchInFlightRef.current) return;

    async function refreshOnce() {
      try {
        fetchInFlightRef.current = true;
        const map = await getRepoBriefs();
        setBriefs(
          Object.fromEntries(
            Object.entries(map).filter(([id]) => !hiddenRepoIds.has(id))
          )
        );
      } catch (e) {
        console.warn("Refresh repo briefs failed:", e);
      } finally {
        fetchInFlightRef.current = false;
      }
    }
    void refreshOnce();
  }, [repoIds, briefs, hiddenRepoIds]);

  useEffect(() => {
    const allIds = new Set(
      Object.values(convosByRepo)
        .flat()
        .map((c) => c.id)
    );
    setHiddenDeletedIds((prev) => {
      if (prev.size === 0) return prev;
      const next = new Set<string>();
      for (const id of prev) {
        if (allIds.has(id)) next.add(id);
      }
      return next;
    });
  }, [convosByRepo]);

  const convoLabel = (c: Conversation) =>
    c.title || c.latest_question || `Conversation ${c.id.slice(0, 8)}`;

  const matchesSearch = (ridLabel: string, c: Conversation) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    const hay = `${ridLabel} ${c.title || ""} ${
      c.latest_question || ""
    }`.toLowerCase();
    return hay.includes(q);
  };

  async function handleDelete(repoId: string, convoId: string) {
    setDeletingId(convoId);
    try {
      if (onDeleteConvo) {
        await onDeleteConvo(repoId, convoId);
      } else {
        const res = await fetch(`/api/conversations/${convoId}`, {
          method: "DELETE",
        });
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(text || `Failed to delete conversation ${convoId}`);
        }
      }

      setHiddenDeletedIds((prev) => {
        const next = new Set(prev);
        next.add(convoId);
        return next;
      });

      onConvoDeleted?.(repoId, convoId);
      window.dispatchEvent(
        new CustomEvent("conversation:deleted", {
          detail: { repoId, convoId },
        })
      );

      toast.success("Conversation deleted");
    } catch (err: any) {
      toast.error(err?.message || "Couldn’t delete conversation");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleDeleteRepo(repoId: string) {
    setRepoDeletingId(repoId);
    try {
      const ok = await deleteRepo(repoId);
      if (!ok) throw new Error("Failed to delete repository");

      setHiddenRepoIds((prev) => new Set(prev).add(repoId));

      setBriefs((prev) => {
        const next = { ...prev };
        delete next[repoId];
        return next;
      });

      onRepoDeleted?.(repoId);
      window.dispatchEvent(
        new CustomEvent("repo:deleted", { detail: { repoId } })
      );
      toast.success("Repository deleted");
    } catch (err: any) {
      toast.error(err?.message || "Couldn’t delete repository");
    } finally {
      setRepoDeletingId(null);
    }
  }

  const repoIcon = (t?: "git" | "upload") =>
    t === "git" ? (
      <Github className="h-3.5 w-3.5 shrink-0 text-slate-500 dark:text-slate-300" />
    ) : (
      <FileArchive className="h-3.5 w-3.5 shrink-0 text-slate-500 dark:text-slate-300" />
    );

  return (
    <aside className="border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-[rgb(10,10,12)] flex flex-col min-h-0">
      <div className="p-3 border-b border-gray-200 dark:border-gray-800 space-y-3">
        <button
          className="w-full inline-flex items-center gap-2 rounded-md border border-gray-300 dark:border-gray-700 px-3 py-2 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800"
          onClick={onNewRepo}
        >
          <Plus className="h-4 w-4" />
          New repo
        </button>

        <div className="relative">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-gray-400" />
          <input
            className="w-full pl-8 pr-2 py-2 text-sm rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900"
            placeholder="Search chats"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto p-2 space-y-1">
        {repoIds.length === 0 && (
          <div className="text-xs text-gray-500 p-2">
            No conversations yet. Click “New repo” to upload a codebase or
            create a chat under an already uploaded repo.
          </div>
        )}

        {repoIds.map((rid) => {
          const isOpen = !!expanded[rid];
          const allConvos = convosByRepo[rid] ?? [];
          const brief = briefs[rid];
          const repoLabel = brief?.label ?? rid;

          const convos = allConvos
            .filter((c) => !hiddenDeletedIds.has(c.id))
            .filter((c) => matchesSearch(repoLabel, c));

          return (
            <div key={rid} className="rounded-md">
              <div className="px-2 py-2 grid grid-cols-[1fr_auto_auto] items-center gap-1">
                <button
                  className="min-w-0 text-left text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 rounded px-2 py-1 truncate inline-flex items-center gap-2"
                  onClick={() => {
                    onToggleRepo(rid);
                    onSelectRepo?.(rid);
                  }}
                  title={repoLabel}
                >
                  {repoIcon(brief?.source_type)}
                  <span className="truncate">
                    {repoLabel}
                    {!namesLoaded && (
                      <span className="ml-2 text-[10px] text-gray-400">
                        (loading…)
                      </span>
                    )}
                  </span>
                </button>

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      className="shrink-0 ml-1 rounded p-1 hover:bg-gray-50 dark:hover:bg-gray-800"
                      onClick={(e) => e.stopPropagation()}
                      aria-label="More"
                      title="More"
                    >
                      <MoreVertical className="h-4 w-4" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onSelect={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        onNewChat(rid);
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Plus className="h-4 w-4 mr-2" />
                      New chat
                    </DropdownMenuItem>

                    <DropdownMenuItem
                      className="text-red-600 dark:text-red-300 focus:text-red-600"
                      onSelect={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDeleteRepoOpenId(rid);
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {repoDeletingId === rid ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <Trash className="h-4 w-4 mr-2" />
                      )}
                      Delete repo
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>

                <button
                  className="shrink-0 ml-1 rounded p-1 hover:bg-gray-50 dark:hover:bg-gray-800"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleRepo(rid);
                  }}
                  aria-label={isOpen ? "Collapse" : "Expand"}
                  title={isOpen ? "Collapse" : "Expand"}
                >
                  {isOpen ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </button>
              </div>

              <AlertDialogPrimitive.Root
                open={deleteRepoOpenId === rid}
                onOpenChange={(open) => {
                  if (!open) setDeleteRepoOpenId(null);
                }}
              >
                <AlertDialogPrimitive.Portal>
                  <AlertDialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
                  <AlertDialogPrimitive.Content
                    className={[
                      "fixed z-50 grid w-full max-w-md gap-4 rounded-lg border bg-white p-6 shadow-lg",
                      "left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
                      "dark:bg-zinc-900 dark:border-zinc-800",
                    ].join(" ")}
                  >
                    <div className="flex flex-col space-y-2 text-center sm:text-left">
                      <AlertDialogPrimitive.Title className="text-lg font-semibold">
                        Delete this repository?
                      </AlertDialogPrimitive.Title>
                      <AlertDialogPrimitive.Description className="text-sm text-gray-600 dark:text-gray-300">
                        This will remove the repo and all its
                        conversations/files. This cannot be undone.
                      </AlertDialogPrimitive.Description>
                    </div>

                    <div className="flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2">
                      <AlertDialogPrimitive.Cancel className="inline-flex items-center justify-center rounded-md px-4 py-2">
                        No
                      </AlertDialogPrimitive.Cancel>
                      <AlertDialogPrimitive.Action
                        className="inline-flex items-center justify-center rounded-md px-4 py-2 bg-red-600 text-white hover:bg-red-700"
                        onClick={async (e) => {
                          e.stopPropagation();
                          await handleDeleteRepo(rid);
                          setDeleteRepoOpenId(null);
                        }}
                      >
                        Yes, delete repo
                      </AlertDialogPrimitive.Action>
                    </div>
                  </AlertDialogPrimitive.Content>
                </AlertDialogPrimitive.Portal>
              </AlertDialogPrimitive.Root>

              {isOpen && (
                <div className="pl-2 pb-2 space-y-1">
                  {convos.length === 0 && (
                    <div className="text-xs text-gray-500 pl-2">
                      {search.trim()
                        ? "No conversations match your search."
                        : "No conversations."}
                    </div>
                  )}

                  {convos.map((c) => {
                    const active = c.id === activeConversationId;
                    const label = convoLabel(c);

                    return (
                      <div
                        key={c.id}
                        className={`group flex items-center gap-2 px-2 py-2 text-xs rounded ${
                          active
                            ? "bg-gray-100 dark:bg-gray-800"
                            : "hover:bg-gray-50 dark:hover:bg-gray-800"
                        }`}
                      >
                        <button
                          className="flex-1 text-left inline-flex items-center gap-2 min-w-0"
                          onClick={() => onSelectConvo(rid, c.id)}
                          title={label || undefined}
                        >
                          <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">{label}</span>
                        </button>

                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <button
                              className="shrink-0 p-1 rounded opacity-80 hover:opacity-100 hover:bg-gray-100 dark:hover:bg-gray-700"
                              onClick={(e) => e.stopPropagation()}
                              aria-label="Delete conversation"
                              title="Delete conversation"
                            >
                              {deletingId === c.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Trash className="h-4 w-4" />
                              )}
                            </button>
                          </AlertDialogTrigger>

                          <AlertDialogContent
                            onClick={(e) => e.stopPropagation()}
                          >
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                Delete this conversation?
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                This action cannot be undone. The conversation
                                and its messages will be permanently deleted.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel
                                onClick={(e) => e.stopPropagation()}
                              >
                                No
                              </AlertDialogCancel>
                              <AlertDialogAction
                                onClick={async (e) => {
                                  e.stopPropagation();
                                  await handleDelete(rid, c.id);
                                }}
                                className="bg-red-600 text-white hover:bg-red-700"
                              >
                                Yes, delete
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
