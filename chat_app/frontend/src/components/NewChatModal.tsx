import { useEffect, useState } from "react";
import type { AgentInfo } from "../types";
import { getAgents } from "../api";

interface Props {
  defaultProject: string;
  recentProjects: string[];
  onClose: () => void;
  onCreate: (target: AgentInfo, project: string, setDefault: boolean) => void;
}

export default function NewChatModal({
  defaultProject,
  recentProjects,
  onClose,
  onCreate,
}: Props) {
  const [project, setProject] = useState(defaultProject);
  const [loadedProject, setLoadedProject] = useState(defaultProject);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [setDefault, setSetDefault] = useState(true);

  function keyOf(a: AgentInfo): string {
    return a.kind === "agent" ? `agent:${a.name}` : `model:${a.model}`;
  }

  async function loadAgents(proj: string) {
    setLoading(true);
    setError(null);
    setAgents([]);
    setSelectedKey(null);
    try {
      const list = await getAgents(proj || undefined);
      setAgents(list.agents);
      setError(list.error);
      setLoadedProject(list.project);
      if (list.agents.length) setSelectedKey(keyOf(list.agents[0]));
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  // Initial load.
  useEffect(() => {
    loadAgents(defaultProject);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function confirm() {
    const target = agents.find((a) => keyOf(a) === selectedKey);
    if (target) onCreate(target, loadedProject, setDefault);
  }

  const projectDirty = project.trim() !== loadedProject;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-neutral-700 bg-neutral-900 p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-1 text-lg font-semibold text-neutral-50">
          Start a new chat
        </h2>
        <p className="mb-4 text-sm text-neutral-400">
          Choose a GCP project, then pick one of its agents.
        </p>

        {/* Project selector */}
        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-400">
          GCP Project
        </label>
        <div className="mb-4 flex gap-2">
          <input
            list="recent-projects"
            value={project}
            onChange={(e) => setProject(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") loadAgents(project.trim());
            }}
            placeholder="my-gcp-project"
            className="flex-1 rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500"
          />
          <datalist id="recent-projects">
            {recentProjects.map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
          <button
            onClick={() => loadAgents(project.trim())}
            disabled={loading}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
              projectDirty
                ? "bg-blue-600 text-white hover:bg-blue-500"
                : "border border-neutral-700 text-neutral-300 hover:bg-neutral-800"
            } disabled:opacity-40`}
          >
            {loading ? "Loading…" : "Load agents"}
          </button>
        </div>

        {error && (
          <p className="mb-3 rounded-lg bg-red-950/50 p-3 text-sm text-red-300">
            {error}
          </p>
        )}

        {!loading && !error && agents.length === 0 && (
          <p className="py-8 text-center text-sm text-neutral-500">
            No agents found in <span className="font-mono">{loadedProject}</span>.
          </p>
        )}

        {!loading && agents.length > 0 && (
          <div className="max-h-72 space-y-1.5 overflow-y-auto">
            {agents.map((a) => {
              const key = keyOf(a);
              const selected = key === selectedKey;
              return (
                <button
                  key={key}
                  onClick={() => setSelectedKey(key)}
                  className={`flex w-full flex-col items-start rounded-lg border px-3 py-2 text-left transition ${
                    selected
                      ? "border-blue-500 bg-blue-950/40"
                      : "border-neutral-700 hover:border-neutral-600"
                  }`}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className="font-medium text-neutral-100">
                      {a.display_name}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                        a.kind === "agent"
                          ? "bg-purple-900/60 text-purple-200"
                          : "bg-neutral-700 text-neutral-300"
                      }`}
                    >
                      {a.kind}
                    </span>
                  </div>
                  {a.description && (
                    <span className="mt-0.5 line-clamp-2 text-xs text-neutral-400">
                      {a.description}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        <label className="mt-4 flex items-center gap-2 text-sm text-neutral-300">
          <input
            type="checkbox"
            checked={setDefault}
            onChange={(e) => setSetDefault(e.target.checked)}
            className="h-4 w-4 accent-blue-600"
          />
          Remember{" "}
          <span className="font-mono text-neutral-200">
            {loadedProject || "this project"}
          </span>{" "}
          as my default for new chats
        </label>

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800"
          >
            Cancel
          </button>
          <button
            onClick={confirm}
            disabled={!selectedKey}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-40"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
