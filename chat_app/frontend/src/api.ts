import type {
  AgentList,
  Config,
  Conversation,
  Health,
  Message,
} from "./types";

const BASE = "/api";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<Health> {
  return json(await fetch(`${BASE}/health`));
}

export async function getConfig(): Promise<Config> {
  return json(await fetch(`${BASE}/config`));
}

export async function getAgents(project?: string): Promise<AgentList> {
  const qs = project ? `?project=${encodeURIComponent(project)}` : "";
  return json(await fetch(`${BASE}/agents${qs}`));
}

export async function listConversations(): Promise<Conversation[]> {
  return json(await fetch(`${BASE}/conversations`));
}

export async function createConversation(input: {
  title?: string;
  agent?: string | null;
  model?: string | null;
  project?: string | null;
  set_default?: boolean;
}): Promise<Conversation> {
  return json(
    await fetch(`${BASE}/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    })
  );
}

export async function renameConversation(
  id: string,
  title: string
): Promise<Conversation> {
  return json(
    await fetch(`${BASE}/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    })
  );
}

export async function deleteConversation(id: string): Promise<void> {
  await json(
    await fetch(`${BASE}/conversations/${id}`, { method: "DELETE" })
  );
}

export async function clearConversation(id: string): Promise<void> {
  await json(
    await fetch(`${BASE}/conversations/${id}/clear`, { method: "POST" })
  );
}


export async function listMessages(convId: string): Promise<Message[]> {
  return json(await fetch(`${BASE}/conversations/${convId}/messages`));
}

export interface StreamHandlers {
  onDelta: (text: string) => void;
  onDone: (info: { message_id: string; interaction_id: string | null }) => void;
  onError: (message: string) => void;
}

/**
 * Send a message and consume the SSE stream of assistant deltas.
 * Returns an AbortController so the caller can stop generation.
 */
export function streamMessage(
  convId: string,
  content: string,
  handlers: StreamHandlers
): AbortController {
  const controller = new AbortController();

  (async () => {
    let res: Response;
    try {
      res = await fetch(`${BASE}/conversations/${convId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
        signal: controller.signal,
      });
    } catch (e) {
      if (!controller.signal.aborted) handlers.onError(String(e));
      return;
    }

    if (!res.ok || !res.body) {
      handlers.onError(`HTTP ${res.status}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          dispatchFrame(frame, handlers);
        }
      }
    } catch (e) {
      if (!controller.signal.aborted) handlers.onError(String(e));
    }
  })();

  return controller;
}

function dispatchFrame(frame: string, handlers: StreamHandlers) {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  let payload: any;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }
  if (event === "delta") handlers.onDelta(payload.text ?? "");
  else if (event === "done") handlers.onDone(payload);
  else if (event === "error") handlers.onError(payload.message ?? "Error");
}
