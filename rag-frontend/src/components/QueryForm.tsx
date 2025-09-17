// src/components/QueryForm.tsx

import { useState, useCallback, useRef, useEffect } from "react";
import { Textarea } from "./ui/textarea";
import { Button } from "./ui/button";
import { toast } from "sonner";
import { useRepoProgress } from "../hooks/useRepoProgress";
import RepoProgress from "./RepoProgress";

interface Props {
  repoId: string;
  onAsk: (question: string) => void;
  onAnswer: (answer: string) => void;
  onSelectFile: (filePath: string, content: string) => void;
  mode?: "full" | "composer";
  ready?: boolean;
  disabled?: boolean;
}

export function QueryForm({
  repoId,
  onAsk,
  onAnswer,
  onSelectFile,
  mode = "full",
  ready,
  disabled: disabledProp,
}: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    phases,
    uploadPct,
    embeddingPct,
    indexingPct,
    overallPct,
    isIndexed,
    hasError,
  } = useRepoProgress(repoId);

  const doneRef = useRef(false);
  const indexingShownRef = useRef(false);
  const keepAliveTimerRef = useRef<number | null>(null);
  const INDEXING_TOAST_ID = `indexing-${repoId}`;

  const clearKeepAlive = () => {
    if (keepAliveTimerRef.current) {
      window.clearTimeout(keepAliveTimerRef.current);
      keepAliveTimerRef.current = null;
    }
  };

  const showIndexingToast = () => {
    toast.custom(
      () => (
        <div
          className="flex items-center gap-3 rounded-md border px-3 py-2
                        bg-amber-50 text-amber-900 border-amber-200
                        dark:bg-amber-950/50 dark:text-amber-200 dark:border-amber-900/50"
        >
          <svg
            className="h-4 w-4 animate-spin"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4z"
            />
          </svg>
          <div className="text-sm font-medium">
            Indexing repository… <span>(this may take a bit)</span>
          </div>
        </div>
      ),
      { id: INDEXING_TOAST_ID, duration: 12_000 }
    );
  };

  useEffect(() => {
    doneRef.current = false;
    indexingShownRef.current = false;
    clearKeepAlive();
    toast.dismiss(INDEXING_TOAST_ID);
  }, [repoId]);

  useEffect(() => {
    const isRunning = phases.indexing.status === "running";

    if (isRunning && !indexingShownRef.current) {
      indexingShownRef.current = true;
      showIndexingToast();

      const tick = () => {
        if (phases.indexing.status === "running") {
          showIndexingToast();
          keepAliveTimerRef.current = window.setTimeout(tick, 5_000);
        } else {
          clearKeepAlive();
        }
      };
      keepAliveTimerRef.current = window.setTimeout(tick, 5_000);
    }

    if (!doneRef.current && isIndexed) {
      doneRef.current = true;
      clearKeepAlive();
      toast.dismiss(INDEXING_TOAST_ID);
      toast.success("Indexing complete!");
    }

    if (!doneRef.current && hasError) {
      doneRef.current = true;
      clearKeepAlive();
      toast.dismiss(INDEXING_TOAST_ID);
      toast.error("Indexing failed. Check logs/status.");
    }

    return () => {
      if (doneRef.current) return;
      if (!isRunning) clearKeepAlive();
    };
  }, [phases.indexing.status, isIndexed, hasError, mode]);

  const parentReady =
    typeof disabledProp === "boolean" ? !disabledProp : !!ready;
  const canAsk = parentReady || isIndexed;

  const sendDisabled = loading || !question.trim() || !canAsk;

  const ask = useCallback(async () => {
    const q = question.trim();
    if (!q) return;
    if (!canAsk) {
      setError("Repository is not ready yet.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      onAsk(q);
      setQuestion("");
    } finally {
      setLoading(false);
    }
  }, [question, canAsk, onAsk]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mode === "composer") {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!sendDisabled) void ask();
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!sendDisabled) void ask();
    }
  };

  return mode === "composer" ? (
    <div className="w-full">
      <div className="rounded-xl border p-2 shadow-sm bg-white dark:bg-zinc-900">
        <Textarea
          placeholder="Ask a question about your code…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={loading}
          className="resize-none border-0 focus-visible:ring-0 focus-visible:outline-none"
          rows={3}
        />
        {error && <div className="text-red-500 text-sm mt-2">{error}</div>}
        <div className="flex items-center justify-end gap-2 mt-2">
          <div className="text-xs text-gray-500 mr-auto">
            {loading ? "Thinking…" : "Shift+Enter for newline • Enter to send"}
          </div>
          <Button onClick={ask} disabled={sendDisabled}>
            {loading ? "Thinking…" : canAsk ? "Send" : "Indexing…"}
          </Button>
        </div>
      </div>
      <div className="h-4 md:h-2" />
    </div>
  ) : (
    <div className="space-y-4">
      <RepoProgress
        upload={{ status: phases.upload.status, pct: uploadPct }}
        embedding={{ status: phases.embedding.status, pct: embeddingPct }}
        indexing={{ status: phases.indexing.status, pct: indexingPct }}
        overallPct={overallPct}
      />

      <Textarea
        placeholder="Ask a question about the codebase… (Ctrl/Cmd+Enter)"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={loading}
      />
      {error && <div className="text-red-500 text-sm">{error}</div>}
      <Button onClick={ask} disabled={sendDisabled}>
        {loading ? "Thinking…" : canAsk ? "Ask" : "Indexing…"}
      </Button>
    </div>
  );
}
