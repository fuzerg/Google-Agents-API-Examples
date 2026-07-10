"""Pydantic request/response models for the chat app API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    authenticated: bool
    project_id: str | None = None
    location: str
    error: str | None = None


class ConfigResponse(BaseModel):
    """Client bootstrap config."""

    default_project: str | None = None
    location: str
    default_model: str
    recent_projects: list[str] = []
    # Whether default_project comes from a saved user preference (vs ADC/env).
    default_project_is_saved: bool = False


class SettingsUpdate(BaseModel):
    # Use empty string / null to clear the saved default project.
    default_project: str | None = None


class SettingsResponse(BaseModel):
    default_project: str | None = None


class AgentInfo(BaseModel):
    """A selectable target: either a custom agent or a base model."""

    # Full resource path for custom agents, or None for base models.
    name: str | None = None
    # Human-friendly label shown in the picker.
    display_name: str
    description: str | None = None
    # 'agent' or 'model'.
    kind: str
    # For base models this is the model id; for agents it's the base_agent.
    model: str | None = None
    # The GCP project this target belongs to.
    project: str | None = None


class AgentListResponse(BaseModel):
    project: str
    agents: list[AgentInfo]
    error: str | None = None


class ConversationCreate(BaseModel):
    title: str | None = None
    # Full agent resource path. None => use a base model.
    agent: str | None = None
    model: str | None = None
    project: str | None = None
    # Remember this project as the default for future new chats.
    set_default: bool = True


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Conversation(BaseModel):
    id: str
    title: str
    agent: str | None = None
    model: str
    project: str | None = None
    last_interaction_id: str | None = None
    created_at: str
    updated_at: str


class Message(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    interaction_id: str | None = None
    status: str
    created_at: str


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)
