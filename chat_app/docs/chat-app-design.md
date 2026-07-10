# Local Chat App for Gemini Interactions API — Design & Execution Plan

A local, ChatGPT/Gemini-style chat application that talks to agents on the Gemini
Enterprise Agent Platform via the **Interactions API** (Data Plane) and lists
agents via the **Managed Agents API** (Control Plane).

---

## 1. Goals & Scope

### Goals
- A polished, local chat UI (single user, runs on your machine).
- Chat with agents that already exist in your GCP project (selectable per conversation).
- Real-time **streaming** responses.
- **Multiple conversation threads** in a sidebar, like ChatGPT/Gemini.
- **Persistent** history across app restarts (local SQLite).

### In scope (v1)
- List existing agents (Control Plane `GET /agents`).
- Fallback: chat directly with a base model (e.g. `gemini-3-flash-preview`) when no custom agent is chosen — keeps the app usable even if the project has zero persistent agents.
- Multi-turn stateful chat using `previous_interaction_id`.
- Streaming via Server-Sent Events (SSE) from backend to frontend.
- Basic markdown + code-block rendering (required for a usable chat UI).
- Conversation CRUD: create, rename, delete, switch.

### Out of scope (v1 — see §10 Future work)
- Creating/editing agents from the UI.
- File uploads / multimodal input.
- Rendering generated artifacts (PDFs/images from output mounts).
- Rich tool-call / code-execution visualization (we'll capture the data but render minimally).
- Multi-user / auth beyond local ADC.

---

## 2. Architecture

```
┌─────────────────────┐    HTTP + SSE    ┌──────────────────────────┐   google-genai SDK   ┌───────────────────────────┐
│   React SPA (Vite)  │ ───────────────► │      FastAPI backend     │ ───────────────────► │  Gemini Interactions API  │
│  - chat window      │ ◄─────────────── │  - REST + SSE endpoints  │ ◄─────────────────── │  (Data Plane, streaming)  │
│  - thread sidebar   │   stream deltas  │  - ADC auth              │                      └───────────────────────────┘
│  - markdown render  │                  │  - conversation store    │       REST (token)   ┌───────────────────────────┐
└─────────────────────┘                  │                          │ ───────────────────► │  Managed Agents API       │
                                         │                          │                      │  (Control Plane, list)    │
                                         │        ▼ SQLite          │                      └───────────────────────────┘
                                         │  conversations, messages │
                                         └──────────────────────────┘
```

**Why this shape:**
- The Interactions API already speaks SSE; the backend forwards those deltas to the browser as SSE. Minimal transformation, true token-by-token streaming.
- FastAPI reuses the `google-genai` SDK and ADC pattern already proven in `showcase/prober.py`.
- The backend owns secrets/tokens and the SQLite store; the React app stays a thin client.

---

## 3. Tech Stack & Dependencies

### Backend (Python 3.10+)
- `fastapi`, `uvicorn[standard]` — API + SSE server (already in `showcase/requirements.txt`).
- `google-genai >= 2.0.0` — Interactions API SDK (**legacy SDKs unsupported**).
- `google-auth` — ADC credentials + access token for Control Plane REST.
- `requests` — Control Plane `list agents` REST call.
- `sqlite3` — stdlib, no dependency; (optional `SQLModel`/`sqlalchemy` if we want an ORM).
- `pydantic` — request/response models (ships with FastAPI).

### Frontend
- `React` + `Vite` + `TypeScript`.
- `react-markdown` + `remark-gfm` + a syntax highlighter (`highlight.js` / `rehype-highlight`) for message rendering.
- Native `fetch` with a streaming reader for SSE (no heavy client lib needed).
- Light styling: Tailwind CSS (fast to build a clean ChatGPT-like layout).

### Environment / Auth
- ADC: `gcloud auth application-default login` (same as the showcase).
- Env vars: `GOOGLE_CLOUD_PROJECT` (or resolved from ADC), `GOOGLE_CLOUD_LOCATION=global`, `GOOGLE_GENAI_USE_ENTERPRISE=true`.

---

## 4. Backend Design

### 4.1 Auth
- On startup, resolve credentials + project via `google.auth.default(scopes=[...cloud-platform])` (mirrors `prober.py`).
- Initialize `genai.Client(enterprise=True, project=project_id, location="global")`.
- For Control Plane list-agents, refresh the ADC token and call REST with a Bearer header.

### 4.2 Data model (SQLite)

```
conversations
  id                TEXT  PRIMARY KEY   -- uuid
  title             TEXT                -- auto from first message, editable
  agent             TEXT  NULL          -- agent resource path, or NULL = base model
  model             TEXT                -- e.g. gemini-3-flash-preview (used when agent is NULL)
  last_interaction_id TEXT NULL         -- for previous_interaction_id chaining
  created_at        TEXT
  updated_at        TEXT

messages
  id                TEXT  PRIMARY KEY   -- uuid
  conversation_id   TEXT  FK
  role              TEXT                -- 'user' | 'assistant'
  content           TEXT                -- full text (markdown)
  interaction_id    TEXT  NULL          -- id returned by the API for assistant turns
  status            TEXT                -- 'complete' | 'error' | 'streaming'
  created_at        TEXT
```

### 4.3 REST + SSE endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/agents` | List agents (Control Plane) + include a synthetic "Base model" option. |
| `GET`  | `/api/conversations` | List conversations for the sidebar. |
| `POST` | `/api/conversations` | Create a conversation (choose agent or base model). |
| `PATCH`| `/api/conversations/{id}` | Rename. |
| `DELETE`| `/api/conversations/{id}` | Delete. |
| `GET`  | `/api/conversations/{id}/messages` | Load message history for a thread. |
| `POST` | `/api/conversations/{id}/messages` | Send a user message; **returns an SSE stream** of assistant deltas. |
| `GET`  | `/api/health` | Auth/project sanity check for the UI. |

### 4.4 Send-message flow (the core)

1. Persist the user message (`role='user'`).
2. Build `interactions.create(...)` kwargs:
   - `agent=<resource path>` **or** `model=<base model>` (whichever the conversation uses).
   - `input=<user text>`
   - `stream=True`, `store=True`
   - `previous_interaction_id=conversation.last_interaction_id` (if present).
3. Iterate the stream. For each event:
   - `event.event_type == "step.delta"` and `delta.type == "text"` → forward `delta.text` as an SSE `data:` chunk and append to an accumulator.
   - `delta.type == "code_execution_result"` (and other tool deltas) → forward as a typed SSE event (rendered minimally in v1, captured for future).
4. On completion: capture the interaction `id`, persist the assistant message (full accumulated text + `interaction_id`), update `conversation.last_interaction_id` and `updated_at`, and emit a final SSE `event: done` carrying `{message_id, interaction_id}`.
5. On error: persist an error message, emit `event: error`.

> Implementation detail to verify during Phase 2: exactly where the interaction `id` surfaces in the streamed events (final chunk vs. per-event `id`). `prober.py` uses `stream=True, background=True`; we will confirm whether `background` is needed for interactive latency or whether plain `stream=True` is snappier. Both are supported.

### 4.5 Streaming transport
- FastAPI `StreamingResponse` with `media_type="text/event-stream"`.
- Run the blocking SDK stream iteration in a threadpool (or use the async client if available) so the event loop isn't blocked.
- Client aborts (user navigates away / stops) cancel the generator.

---

## 5. Frontend Design

### Layout (ChatGPT/Gemini-style)
```
┌───────────────┬─────────────────────────────────────┐
│  Sidebar      │  Header: [agent/model selector]      │
│  [+ New chat] ├─────────────────────────────────────┤
│  • Chat A     │                                       │
│  • Chat B     │   message list (user / assistant      │
│  • Chat C     │   bubbles, markdown + code blocks)     │
│   ...         │                                       │
│               ├─────────────────────────────────────┤
│               │  composer: [ textarea ] [ Send ]      │
└───────────────┴─────────────────────────────────────┘
```

### Components
- `App` — layout + routing/state.
- `Sidebar` — conversation list, new-chat, rename/delete.
- `ChatView` — message list + auto-scroll.
- `Message` — role-styled bubble, `react-markdown` rendering, streaming cursor.
- `Composer` — textarea, submit on Enter, stop button while streaming.
- `AgentPicker` — dropdown from `GET /api/agents` (shown on new-chat creation).

### State & streaming
- Fetch conversations + messages via REST.
- On send: append optimistic user bubble + empty assistant bubble; `POST` the message and read the SSE stream with `fetch` + `ReadableStream` reader; append text deltas to the assistant bubble as they arrive.
- On `done`: finalize the bubble (store message id / interaction id).
- Minimal client state library — React state/context is enough; optional Zustand if it grows.

---

## 6. Integration Details (grounded in the API skills)

- **List agents (Control Plane):** `GET https://aiplatform.googleapis.com/v1beta1/projects/{PROJECT}/locations/global/agents` with `Authorization: Bearer <ADC token>`; response `{ "agents": [ { name, description, base_agent, ... } ] }`. The `name` (full resource path) is what we pass as `agent` to interactions.
- **Interactions (Data Plane):** `client.interactions.create(agent=..., input=..., stream=True, store=True, previous_interaction_id=...)`. Multi-turn continuity is via `previous_interaction_id` (server-side stored state), so we only persist IDs + a local copy of text.
- **Models:** default base model `gemini-3-flash-preview` (or `gemini-2.5-flash`). Legacy `gemini-2.0-*` / `1.5-*` are deprecated and unsupported.
- **Turn-scoped params:** `tools` / `system_instruction` / `generation_config` must be sent each turn — for v1 with existing agents these live on the agent, so we don't resend them; relevant only if we add base-model system prompts later.

---

## 7. Project Structure

```
interactions_api/
└── chat_app/
    ├── backend/
    │   ├── main.py            # FastAPI app + CORS + static serving
    │   ├── auth.py            # ADC credentials + token refresh + genai client
    │   ├── agents.py          # Control Plane list agents
    │   ├── interactions.py    # send-message streaming logic
    │   ├── db.py              # SQLite schema + queries
    │   ├── models.py          # pydantic request/response models
    │   └── requirements.txt
    └── frontend/
        ├── index.html
        ├── package.json
        ├── vite.config.ts
        └── src/
            ├── main.tsx
            ├── App.tsx
            ├── api.ts         # REST + SSE client
            ├── components/    # Sidebar, ChatView, Message, Composer, AgentPicker
            └── styles.css
```

Dev: Vite dev server (`:5173`) proxies `/api` to FastAPI (`:8000`).
Prod-local: `npm run build` → FastAPI serves the static `dist/` so the whole app runs from one `uvicorn` process.

---

## 8. Execution Plan (phased)

### Phase 0 — Scaffolding (foundation)
- Create `chat_app/` structure, backend venv + requirements, Vite React+TS app + Tailwind.
- `GET /api/health` returns resolved project + auth status; wire the dev proxy.
- **Milestone:** app loads, health check green.

### Phase 1 — Agents + conversations (no streaming yet)
- `auth.py` + `genai.Client`; `GET /api/agents` (Control Plane) with a "Base model" fallback entry.
- SQLite `db.py`; conversation CRUD endpoints; sidebar + new-chat + agent picker in UI.
- **Milestone:** create/switch/rename/delete conversations; pick an agent or base model.

### Phase 2 — Streaming chat (the core)
- `interactions.py` send-message with `stream=True, store=True`, `previous_interaction_id` chaining.
- SSE `StreamingResponse`; capture + persist interaction id; frontend SSE reader renders live deltas.
- Persist user + assistant messages; reload history on thread switch.
- **Milestone:** full multi-turn streaming chat that survives restart.

### Phase 3 — Polish
- Markdown + syntax highlighting, auto-scroll, stop-generation, error states, empty/loading states.
- Auto-title conversations from the first user message.
- Minimal rendering of tool/code-execution deltas (collapsible raw block).
- **Milestone:** feels like ChatGPT/Gemini for text chat.

### Phase 4 — Hardening & docs
- Cancellation on client disconnect, token refresh mid-stream, graceful API errors.
- `README.md` with setup (`gcloud auth application-default login`, run commands).
- Optional: single-command launcher (build frontend + serve via uvicorn).
- **Milestone:** documented, runnable end-to-end.

---

## 9. Risks & Open Questions
- **No persistent agents in project:** the showcase creates ephemeral agents; base-model fallback mitigates this so the app is always usable.
- **Interaction id surfacing in stream:** confirm exact field during Phase 2 (needed for `previous_interaction_id`).
- **`background=True` vs `stream=True` latency:** validate which gives the snappiest interactive feel.
- **Blocking SDK in async server:** run stream iteration in a threadpool or use async client to avoid stalling FastAPI.
- **Token expiry on long streams:** refresh ADC token proactively (pattern exists in `prober.py`).

## 10. Future Work (deferred from v1)
- Agent creation/editing in-app (Control Plane CRUD).
- Multimodal file uploads.
- Rendering generated artifacts (PDF/image output mounts, GCS sync like `prober.py`).
- Rich tool-call timeline (searches, code execution, function calls).
- Response regeneration, edit-and-resend, export conversation.
```
