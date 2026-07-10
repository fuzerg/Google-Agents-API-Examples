import { useMemo, useState } from "react";
import type { Conversation } from "../types";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

interface Group {
  key: string;
  label: string; // short agent id or model name
  project: string | null;
  items: Conversation[];
}

function shortName(c: Conversation): string {
  if (c.agent) return c.agent.split("/").pop() || c.agent;
  return c.model || "Base model";
}

function groupConversations(conversations: Conversation[]): Group[] {
  const map = new Map<string, Group>();
  for (const c of conversations) {
    const key = c.agent ?? `model:${c.model}`;
    let g = map.get(key);
    if (!g) {
      g = { key, label: shortName(c), project: c.project, items: [] };
      map.set(key, g);
    }
    g.items.push(c);
  }
  // Sort items within a group by recency, and groups by their most recent item.
  const groups = [...map.values()];
  for (const g of groups) {
    g.items.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }
  groups.sort((a, b) =>
    b.items[0].updated_at.localeCompare(a.items[0].updated_at),
  );
  return groups;
}

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNewChat,
  onRename,
  onDelete,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const groups = useMemo(
    () => groupConversations(conversations),
    [conversations],
  );

  function startEdit(c: Conversation) {
    setEditingId(c.id);
    setDraft(c.title);
  }

  function commitEdit(id: string) {
    const t = draft.trim();
    if (t) onRename(id, t);
    setEditingId(null);
  }

  function toggle(key: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <aside className="flex h-full w-72 flex-col border-r border-neutral-800 bg-neutral-950">
      <div className="shrink-0 p-3">
        <button
          onClick={onNewChat}
          className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm font-medium text-neutral-100 transition hover:bg-neutral-700"
        >
          + New chat
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 && (
          <p className="px-3 py-6 text-center text-sm text-neutral-500">
            No conversations yet.
          </p>
        )}

        {groups.map((g) => {
          const isCollapsed = collapsed.has(g.key);
          return (
            <div key={g.key} className="mb-2">
              {/* Group header (agent) */}
              <button
                onClick={() => toggle(g.key)}
                className="flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-left"
                title={g.project ? `${g.label} · ${g.project}` : g.label}
              >
                <span className="w-3 shrink-0 text-[10px] text-neutral-500">
                  {isCollapsed ? "▶" : "▼"}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-xs font-semibold uppercase tracking-wide text-neutral-400">
                    {g.label}
                  </span>
                  {g.project && (
                    <span className="truncate text-[10px] text-neutral-600">
                      {g.project}
                    </span>
                  )}
                </span>
                <span className="shrink-0 rounded-full bg-neutral-800 px-1.5 text-[10px] text-neutral-400">
                  {g.items.length}
                </span>
              </button>

              {/* Conversations within the group */}
              {!isCollapsed &&
                g.items.map((c) => {
                  const active = c.id === activeId;
                  return (
                    <div
                      key={c.id}
                      className={`group ml-3 mb-0.5 flex items-center gap-1 rounded-lg px-2 py-2 text-sm ${
                        active
                          ? "bg-neutral-800 text-neutral-50"
                          : "text-neutral-300 hover:bg-neutral-900"
                      }`}
                    >
                      {editingId === c.id ? (
                        <input
                          autoFocus
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onBlur={() => commitEdit(c.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commitEdit(c.id);
                            if (e.key === "Escape") setEditingId(null);
                          }}
                          className="w-full rounded bg-neutral-700 px-2 py-1 text-neutral-50 outline-none"
                        />
                      ) : (
                        <>
                          <button
                            onClick={() => onSelect(c.id)}
                            className="flex-1 truncate text-left"
                            title={c.title}
                          >
                            {c.title}
                          </button>
                          <button
                            onClick={() => startEdit(c)}
                            className="hidden shrink-0 rounded px-1 text-neutral-400 hover:text-neutral-100 group-hover:block"
                            title="Rename"
                          >
                            ✎
                          </button>
                          <button
                            onClick={() => {
                              if (confirm(`Delete "${c.title}"?`)) onDelete(c.id);
                            }}
                            className="hidden shrink-0 rounded px-1 text-neutral-400 hover:text-red-400 group-hover:block"
                            title="Delete"
                          >
                            🗑
                          </button>
                        </>
                      )}
                    </div>
                  );
                })}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
