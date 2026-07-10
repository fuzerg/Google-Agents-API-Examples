# Gemini Interactions Chat (local app)

A local, ChatGPT/Gemini-style chat UI that talks to agents on the Gemini
Enterprise Agent Platform via the **Interactions API**. FastAPI backend +
React (Vite) frontend + local SQLite persistence.

> Status: **Phase 0 + 1 + 2 complete** — health check, per-project agent
> listing (Control Plane), conversation/message persistence + CRUD, and
> **streaming multi-turn chat** with server-side context via
> `previous_interaction_id`.
>
> Notes learned against the live API:
> - Agent interactions **require `background=True`** (plus `stream`, `store`).
> - Raw base models often return "Unsupported model interaction" — this project
>   supports interactions **only via custom agents**, so the base-model picker
>   is empty by default (opt in via `CHAT_APP_BASE_MODELS`).
> - You can chat with agents from **any GCP project** you can access; pick the
>   project in the New Chat dialog.

## Prerequisites

- Python 3.10+ with the repo `venv` (already has fastapi, uvicorn, google-genai).
- Node.js 18+ and npm (for the frontend build/dev server).
- Application Default Credentials:
  ```bash
  gcloud auth application-default login
  ```
- A GCP project with Vertex AI enabled. The app resolves the project from ADC,
  or you can set `GOOGLE_CLOUD_PROJECT`.

## Layout

```
chat_app/
├── backend/     FastAPI app (auth, agents, conversations, SQLite)
├── frontend/    React + Vite + Tailwind SPA
├── dev.sh       Runs backend (:8000) + Vite dev server (:5173)
└── README.md
```

## Run — development (hot reload)

```bash
./chat_app/dev.sh
```

Then open http://localhost:5173. The Vite dev server proxies `/api` to the
FastAPI backend on `:8000`.

### Or run each side manually

Backend:
```bash
cd chat_app/backend
../../venv/bin/python3 -m uvicorn main:app --reload --port 8000
```

Frontend:
```bash
cd chat_app/frontend
npm install        # first time only
npm run dev
```

## Run — single-process local (built frontend served by FastAPI)

```bash
cd chat_app/frontend && npm run build
cd ../backend && ../../venv/bin/python3 -m uvicorn main:app --port 8000
```

Open http://localhost:8000 — FastAPI serves the built SPA and the API from one
origin.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | resolved from ADC | GCP project id |
| `GOOGLE_CLOUD_LOCATION` | `global` | API location |
| `CHAT_APP_DEFAULT_MODEL` | `gemini-3-flash-preview` | base model default |
| `CHAT_APP_BASE_MODELS` | `gemini-3-flash-preview,gemini-2.5-pro,gemini-2.5-flash` | picker options |
| `CHAT_APP_DB_PATH` | `backend/data/chat.db` | SQLite path |
| `CHAT_APP_CORS_ORIGINS` | `http://localhost:5173,...` | dev CORS origins |

### Default project

New chats pre-fill a **default GCP project** so you don't have to retype it:
- The **New Chat** dialog has a "Remember … as my default for new chats"
  checkbox (checked by default). Creating a chat saves that project.
- The saved default persists across restarts (SQLite `app_settings`) and takes
  precedence over the `GOOGLE_CLOUD_PROJECT`/ADC default.
- Endpoints: `GET/PUT /api/settings` (`{ "default_project": "..." }`); send an
  empty string to clear it and fall back to the ADC/env default.

## API endpoints

- `GET /api/health` — auth + project status
- `GET /api/config` — default project, location, recent projects
- `GET /api/agents?project=<id>` — custom agents for a project (Control Plane)
- `GET/POST /api/conversations`, `PATCH/DELETE /api/conversations/{id}`
- `GET /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/messages` — **SSE streaming** send-message

### Streaming protocol (SSE)

`POST /api/conversations/{id}/messages` returns `text/event-stream` with frames:
- `event: delta` → `{ "text": "..." }` (append to the assistant message)
- `event: done` → `{ "message_id", "interaction_id" }`
- `event: error` → `{ "message", "message_id" }`

## Notes

- If `node`/`npm` are missing, install Node.js (the official nodejs.org build is
  recommended on macOS). Update `NODE_BIN` in `dev.sh` if your install path
  differs.
- Legacy SDKs (`google-cloud-aiplatform`, `google-generativeai`) and legacy
  models (`gemini-2.0-*`, `gemini-1.5-*`) are **not** supported by the
  Interactions API.
