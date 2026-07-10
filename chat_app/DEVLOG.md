# Chat App — Dev Log

A running log of the design, decisions, and changes for the local Gemini
Interactions chat app (`chat_app/`). Newest changes are appended under
**Change history**. Keep this file updated as work progresses.

---

## 1. Overview

A local, ChatGPT/Gemini-style chat application for talking to agents on the
Gemini Enterprise Agent Platform via the **Interactions API** (Data Plane), with
agents discovered through the **Managed Agents API** (Control Plane).

- Single user, runs on your machine.
- Chat with agents that already exist in a GCP project (selectable per chat).
- Real-time streaming responses, multi-thread history, local persistence.

---

## 2. Initial design & planning

### Goals
- Polished local chat UI.
- Pick an agent (from any accessible GCP project) per conversation.
- Streaming responses; multiple conversation threads; persistent history.

### Tech stack (decided up front)
- **Backend:** FastAPI (Python), reusing the `google-genai` SDK + ADC auth
  (same pattern as `showcase/prober.py`).
- **Frontend:** React + Vite + TypeScript + Tailwind CSS (v4).
- **Storage:** local **SQLite**.
- **Transport:** Server-Sent Events (SSE) from backend → browser (the
  Interactions API already streams via SSE; the backend forwards deltas).

### Architecture
```
React SPA (Vite)  --HTTP + SSE-->  FastAPI backend  --google-genai-->  Interactions API (Data Plane)
                                        |            --REST (token)-->  Managed Agents API (Control Plane)
                                        v
                                   SQLite (conversations, messages, settings)
```
- Multi-turn continuity is server-side via `previous_interaction_id`; SQLite
  keeps a local index + message text (required — see API constraints below).
- One `uvicorn` process can also serve the built SPA for single-process local use.

### Data model (SQLite)
- `conversations(id, title, agent, model, project, last_interaction_id, created_at, updated_at)`
- `messages(id, conversation_id, role, content, interaction_id, status, created_at)`
- `app_settings(key, value)` — e.g. `default_project`.

### Planned phases
- **Phase 0** — scaffolding, `/api/health`, dev proxy.
- **Phase 1** — agent listing + conversation CRUD + sidebar.
- **Phase 2** — streaming send-message (SSE) + multi-turn.
- **Phase 3** — polish (markdown, auto-scroll, stop, auto-title).
- **Phase 4** — hardening + docs.

Full original design doc: [`docs/chat-app-design.md`](docs/chat-app-design.md).

---

## 3. Project structure

```
chat_app/
├── backend/
│   ├── config.py        # env-driven settings, Control Plane URL
│   ├── auth.py          # ADC creds, token refresh, per-project genai client
│   ├── agents.py        # Control Plane: list agents (per project)
│   ├── db.py            # SQLite schema + queries (+ app_settings)
│   ├── interactions.py  # SSE streaming send-message endpoint
│   ├── models.py        # pydantic request/response models
│   ├── main.py          # FastAPI app, routes, static SPA serving
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx      # state, bootstrap (retry), layout
│       ├── api.ts       # REST + SSE client
│       ├── types.ts
│       └── components/  # Sidebar, ChatView, Message, Composer, NewChatModal
├── docs/
│   └── chat-app-design.md   # original design & execution plan
├── dev.sh               # runs backend :8000 + Vite :5173
├── README.md
└── DEVLOG.md            # this file
```

### API endpoints
- `GET /api/health` — auth + project status
- `GET /api/config` — default project, location, recent projects
- `GET /api/settings`, `PUT /api/settings` — persistent default project
- `GET /api/agents?project=<id>` — agents for a project (Control Plane)
- `GET/POST /api/conversations`, `PATCH/DELETE /api/conversations/{id}`
- `GET /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/messages` — **SSE streaming** send-message
  (frames: `event: delta|done|error`)

---

## 4. Key findings / API constraints (learned during build)

- **Agent interactions require `background=True`** (plus `stream=True`,
  `store=True`). Without it: "Agent interactions must set background to true."
- **Base models are unsupported for interactions** in this project (raw
  `model=...` returns "Unsupported model interaction"), so the app is
  agent-centric; the base-model picker is empty by default
  (`CHAT_APP_BASE_MODELS` to opt in).
- Streaming events: `interaction.created` / `interaction.completed` carry
  `event.interaction.id`; text arrives on `step.delta` where
  `delta.type == "text"` via `delta.text`.
- **The Interactions API cannot back the chat list/history by itself:**
  - No `interactions.list()` method — cannot enumerate conversations.
  - `get(id)` returns only `{id, status, output_text, steps, usage,
    environment_id, object}` — it does **not** return `previous_interaction_id`,
    `input`, `agent`, or timestamps (verified live).
  - Therefore local storage is required for the sidebar, titles, user messages,
    and grouping/sorting. `store=True`/`previous_interaction_id` exist for the
    model's server-side context, not as a client history API.

---

## 5. Change history

### 2026-07-09 — Phase 0 + 1 (scaffolding, agents, CRUD)
- Created `chat_app/` backend + frontend.
- Backend: `config`, `auth` (ADC + genai client), `agents` (Control Plane list),
  `db` (SQLite), `models`, `main`; `/api/health`, agent listing, conversation
  CRUD, message history endpoints; serves built SPA with SPA fallback.
- Frontend: sidebar, new-chat modal with agent picker, conversation
  switching/rename/delete, health banner, project footer.
- Env note: Homebrew Node's shared-`libnode` build was killed by the OS; installed
  official Node v24.18.0 to `~/.local/node/...` (referenced by `dev.sh`).
- Verified: health authenticated, real agents listed, CRUD works, SPA served.

### 2026-07-09 — Phase 2 (streaming chat) + project customization
- `interactions.py`: SSE `POST /api/conversations/{id}/messages` using
  `interactions.create(agent=…, stream=True, store=True, background=True,
  previous_interaction_id=…)`; forwards `delta`/`done`/`error`; persists the
  assistant message + interaction id; blocking SDK iteration runs in Starlette's
  threadpool.
- Frontend: `streamMessage` SSE reader, live token rendering, enabled composer,
  Stop button, markdown/code rendering, auto-title, auto-select most recent chat.
- **Project customization:** per-project `genai` client cache; `GET /api/config`;
  `GET /api/agents?project=`; conversations store their `project`; New Chat dialog
  has a GCP project field + recent-projects dropdown.
- Dropped base models from the picker by default (unsupported for interactions).
- Verified: streaming, multi-turn context (incl. across restart), persistence.

### 2026-07-09 — Layout fixes (multi-turn UI bugs)
- Root cause: missing `min-h-0` on nested flex containers → message list grew
  instead of scrolling, pushing the footer and preventing sidebar scroll.
- Fix: `min-h-0` on `main`, `ChatView` root + message list, and sidebar nav;
  `overflow-hidden` on app root; `shrink-0` on footer + "New chat".
- Result: composer + footer pinned; message area and sidebar scroll independently.

### 2026-07-09 — Open-source UI evaluation (assistant-ui spike)
- Researched Open WebUI / LibreChat / Lobe Chat (all expect OpenAI-compatible
  endpoints; Open WebUI has a branding-restricted license), Chainlit, assistant-ui.
- Built a working **assistant-ui** spike wired to our unchanged backend
  (`LocalRuntime` adapter over our SSE). Decision: **keep the custom UI.**
- Spike later removed (see below).

### 2026-07-09 — Persistent default project
- Backend: `app_settings` table + `db.get_setting/set_setting`; `GET /api/config`
  returns saved default (`default_project_is_saved`); auto-remember on chat
  create when `set_default` true; `GET/PUT /api/settings` for explicit set/clear.
- Frontend: New Chat modal "Remember … as my default for new chats" checkbox
  (default on); modal prefers saved default; config refreshes after create.
- Verified: default persists across restart (saved in the same SQLite DB).

### 2026-07-09 — Sidebar grouped by agent
- `Sidebar.tsx` groups conversations by agent (resource path); collapsible group
  headers show agent name + project + count; groups and items sorted by recency.

### 2026-07-10 — Startup-race fix + dev.sh hardening
- Symptom investigated: app looked "reset" after restart. Root cause was a
  startup race (Vite serves :5173 instantly while uvicorn on :8000 is still
  starting; initial fetches failed silently → empty app). Persistence itself was
  proven correct.
- `App.tsx`: bootstrap with retry/backoff — polls `/api/health` until reachable,
  then loads config + conversations; shows a **"Connecting to backend…"** gate
  meanwhile. Verified via headless browser (connecting → auto-loads on backend up).
- `dev.sh`: pre-flight `pkill -f "uvicorn main:app"` to clear a stale backend
  lingering on :8000 (does not touch the DB).

### 2026-07-10 — Cleanup
- Removed the `spike-assistant-ui/` directory (~670 MB) and its references.

---

## 6. Known issues / incidents

- **Data-loss incident (2026-07-10):** during testing, the agent repeatedly ran
  `rm -f backend/data/chat.db` to reset test state, which deleted the user's real
  chat history. No backup existed (dir is gitignored; no Time Machine) → the
  prior history was unrecoverable. The persistence code was correct; the deletion
  was a testing mistake. **Mitigation going forward:** never delete the real DB;
  use `CHAT_APP_DB_PATH` (e.g. `/tmp/chat_test.db`) for tests.

---

## 7. Open items / TODO

- [ ] Optional: **auto-backup on startup** — copy `chat.db` to
      `data/backups/chat-<timestamp>.db`, keep last ~10 (guards against loss).
- [ ] Optional: **mid-session reconnect** — toast + auto-recover when the backend
      restarts (e.g. from `--reload`).
- [ ] Sidebar group **collapse behavior** — all expanded vs. remember per agent.
- [ ] (Deferred) tool/code-execution event rendering, file uploads, artifact
      rendering, in-app agent creation.

---

## 8. Run / configure

```bash
gcloud auth application-default login      # once
./chat_app/dev.sh                          # backend :8000 + Vite :5173 → http://localhost:5173
```

Key env vars (see `backend/config.py`): `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION` (default `global`), `CHAT_APP_DEFAULT_MODEL`,
`CHAT_APP_BASE_MODELS` (default empty), `CHAT_APP_DB_PATH`
(default `backend/data/chat.db`), `CHAT_APP_CORS_ORIGINS`.

---

## 9. Maintenance convention

When you make a change, add a dated bullet under **Change history** (what +
why), update **Open items** and **Project structure/endpoints** if they changed,
and record any incidents under **Known issues**.
