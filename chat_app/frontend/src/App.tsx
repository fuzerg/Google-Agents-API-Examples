import { useEffect, useRef, useState } from "react";
import type {
  AgentInfo,
  Config,
  Conversation,
  Health,
  Message,
} from "./types";
import {
  createConversation,
  deleteConversation,
  getConfig,
  getHealth,
  listConversations,
  listMessages,
  renameConversation,
  streamMessage,
} from "./api";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import NewChatModal from "./components/NewChatModal";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [showNewChat, setShowNewChat] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [connected, setConnected] = useState(false);
  const [attempts, setAttempts] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const active = conversations.find((c) => c.id === activeId) ?? null;

  // Bootstrap with retry/backoff so a not-yet-ready backend (e.g. Vite serves
  // :5173 instantly while uvicorn on :8000 is still starting, or a --reload
  // restart) never renders an empty, apparently-"reset" app.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let delay = 400;
      // Phase 1: wait until the backend is reachable.
      for (let i = 1; !cancelled; i++) {
        setAttempts(i);
        try {
          const h = await getHealth();
          if (cancelled) return;
          setHealth(h);
          break;
        } catch {
          await sleep(delay);
          delay = Math.min(Math.round(delay * 1.5), 3000);
        }
      }
      if (cancelled) return;
      // Phase 2: load config + conversations (backend is up now).
      try {
        const [cfg, list] = await Promise.all([
          getConfig(),
          listConversations(),
        ]);
        if (cancelled) return;
        setConfig(cfg);
        setConversations(list);
        setActiveId((cur) => cur ?? list[0]?.id ?? null);
      } catch {
        // Non-fatal: render anyway; user can retry actions.
      }
      if (!cancelled) setConnected(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function refreshConversations() {
    const list = await listConversations();
    setConversations(list);
    return list;
  }

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    listMessages(activeId).then(setMessages).catch(() => setMessages([]));
  }, [activeId]);

  async function handleCreate(
    target: AgentInfo,
    project: string,
    setDefault: boolean,
  ) {
    setShowNewChat(false);
    const conv = await createConversation({
      title: "New chat",
      agent: target.kind === "agent" ? target.name : null,
      model: target.model ?? undefined,
      project,
      set_default: setDefault,
    });
    await refreshConversations();
    setActiveId(conv.id);
    // Refresh config so the saved default project stays current for next time.
    getConfig().then(setConfig).catch(() => {});
  }

  async function handleRename(id: string, title: string) {
    await renameConversation(id, title);
    await refreshConversations();
  }

  async function handleDelete(id: string) {
    await deleteConversation(id);
    const list = await refreshConversations();
    if (activeId === id) setActiveId(list[0]?.id ?? null);
  }

  function handleSend(text: string) {
    if (!activeId || streaming) return;

    const userMsg: Message = tempMessage(activeId, "user", text);
    const assistantMsg: Message = tempMessage(activeId, "assistant", "");
    assistantMsg.status = "streaming";
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setStreaming(true);

    abortRef.current = streamMessage(activeId, text, {
      onDelta: (delta) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: m.content + delta }
              : m
          )
        );
      },
      onDone: async () => {
        setStreaming(false);
        abortRef.current = null;
        // Reconcile with server (real ids, interaction id, title/order).
        if (activeId) {
          const [msgs] = await Promise.all([
            listMessages(activeId),
            refreshConversations(),
          ]);
          setMessages(msgs);
        }
      },
      onError: (message) => {
        setStreaming(false);
        abortRef.current = null;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  status: "error",
                  content:
                    (m.content ? m.content + "\n\n" : "") +
                    `⚠️ ${message}`,
                }
              : m
          )
        );
      },
    });
  }

  function handleStop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    // Reload to reflect whatever was persisted server-side.
    if (activeId) listMessages(activeId).then(setMessages).catch(() => {});
  }

  if (!connected) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-neutral-900 text-neutral-300">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-neutral-600 border-t-neutral-200" />
        <p className="text-sm">Connecting to backend…</p>
        {attempts > 2 && (
          <p className="max-w-sm text-center text-xs text-neutral-500">
            Waiting for the API on :8000 (attempt {attempts}). If this persists,
            make sure the backend is running.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-neutral-900 text-neutral-100">
      {health && !health.authenticated && (
        <div className="bg-red-950 px-4 py-2 text-center text-sm text-red-200">
          Not authenticated:{" "}
          {health.error ?? "run `gcloud auth application-default login`"}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={setActiveId}
          onNewChat={() => setShowNewChat(true)}
          onRename={handleRename}
          onDelete={handleDelete}
        />
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <ChatView
            conversation={active}
            messages={messages}
            streaming={streaming}
            onSend={handleSend}
            onStop={handleStop}
          />
        </main>
      </div>

      {config?.default_project && (
        <div className="shrink-0 border-t border-neutral-800 bg-neutral-950 px-4 py-1 text-right text-[11px] text-neutral-500">
          {active?.project ? `chat project: ${active.project} · ` : ""}
          default: {config.default_project} · {config.location}
        </div>
      )}

      {showNewChat && config && (
        <NewChatModal
          defaultProject={config.default_project ?? active?.project ?? ""}
          recentProjects={config.recent_projects}
          onClose={() => setShowNewChat(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  );
}

let _tmp = 0;
function tempMessage(
  conversationId: string,
  role: "user" | "assistant",
  content: string
): Message {
  return {
    id: `temp-${Date.now()}-${_tmp++}`,
    conversation_id: conversationId,
    role,
    content,
    interaction_id: null,
    status: "complete",
    created_at: new Date().toISOString(),
  };
}
