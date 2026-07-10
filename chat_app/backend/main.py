"""FastAPI application entrypoint for the local Gemini chat app.

Phase 0 + 1: health check, agent listing, and conversation/message CRUD.
Phase 2 will add the streaming send-message endpoint (see interactions.py).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import agents as agents_mod
import auth
import db
from config import get_settings
from models import (
    AgentInfo,
    AgentListResponse,
    ConfigResponse,
    Conversation,
    ConversationCreate,
    ConversationRename,
    HealthResponse,
    Message,
    SettingsResponse,
    SettingsUpdate,
)

settings = get_settings()

app = FastAPI(title="Gemini Interactions Chat", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# --------------------------------------------------------------------------- #
# Health & agents
# --------------------------------------------------------------------------- #
@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(**auth.health())


@app.get("/api/config", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    # A saved user preference takes precedence over the ADC/env default.
    saved = db.get_setting("default_project")
    if saved:
        default_project: str | None = saved
        is_saved = True
    else:
        try:
            default_project = auth.get_default_project_id()
        except auth.AuthError:
            default_project = None
        is_saved = False
    recent = db.list_recent_projects()
    return ConfigResponse(
        default_project=default_project,
        location=settings.location,
        default_model=settings.default_model,
        recent_projects=recent,
        default_project_is_saved=is_saved,
    )


@app.get("/api/settings", response_model=SettingsResponse)
def get_app_settings() -> SettingsResponse:
    return SettingsResponse(default_project=db.get_setting("default_project"))


@app.put("/api/settings", response_model=SettingsResponse)
def update_app_settings(body: SettingsUpdate) -> SettingsResponse:
    # Empty string clears the saved preference (falls back to ADC/env).
    value = (body.default_project or "").strip() or None
    db.set_setting("default_project", value)
    return SettingsResponse(default_project=db.get_setting("default_project"))


@app.get("/api/agents", response_model=AgentListResponse)
def get_agents(
    project: str | None = Query(default=None, description="GCP project id"),
) -> AgentListResponse:
    try:
        result = agents_mod.list_agents(project)
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return AgentListResponse(
        project=result["project"],
        agents=[AgentInfo(**a) for a in result["agents"]],
        error=result["error"],
    )


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #
@app.get("/api/conversations", response_model=list[Conversation])
def list_conversations() -> list[Conversation]:
    return [Conversation(**c) for c in db.list_conversations()]


@app.post("/api/conversations", response_model=Conversation)
def create_conversation(body: ConversationCreate) -> Conversation:
    model = body.model or settings.default_model
    title = body.title or "New chat"
    # Prefer explicit project; else derive from the agent resource path; else
    # fall back to the resolved default project.
    project = body.project
    if not project and body.agent and body.agent.startswith("projects/"):
        parts = body.agent.split("/")
        if len(parts) >= 2:
            project = parts[1]
    if not project:
        try:
            project = auth.get_default_project_id()
        except auth.AuthError:
            project = None
    conv = db.create_conversation(
        title=title, agent=body.agent, model=model, project=project
    )
    # Remember the project used so future new chats default to it.
    if project and body.set_default:
        db.set_setting("default_project", project)
    return Conversation(**conv)


@app.get("/api/conversations/{conv_id}", response_model=Conversation)
def get_conversation(conv_id: str) -> Conversation:
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Conversation(**conv)


@app.patch("/api/conversations/{conv_id}", response_model=Conversation)
def rename_conversation(conv_id: str, body: ConversationRename) -> Conversation:
    conv = db.rename_conversation(conv_id, body.title)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Conversation(**conv)


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str) -> dict:
    if not db.delete_conversation(conv_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}


@app.get(
    "/api/conversations/{conv_id}/messages", response_model=list[Message]
)
def list_messages(conv_id: str) -> list[Message]:
    if not db.get_conversation(conv_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [Message(**m) for m in db.list_messages(conv_id)]


# --------------------------------------------------------------------------- #
# Send message (Phase 2: streaming via Interactions API)
# --------------------------------------------------------------------------- #
# Implemented in Phase 2 in interactions.py and mounted here.
try:
    from interactions import register_message_routes

    register_message_routes(app)
except ImportError:
    pass


# --------------------------------------------------------------------------- #
# Static frontend (production build). Served last so /api/* wins.
# --------------------------------------------------------------------------- #
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        index = _FRONTEND_DIST / "index.html"
        return FileResponse(index)
