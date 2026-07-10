"""Streaming send-message endpoint backed by the Gemini Interactions API.

Exposes POST /api/conversations/{id}/messages which streams the assistant's
response back to the browser as Server-Sent Events (SSE). Multi-turn context is
maintained server-side via previous_interaction_id.

Key API constraints (confirmed against the live API):
- Agent interactions MUST set background=True (and stream=True, store=True).
- The interaction id surfaces on `interaction.created` / `interaction.completed`
  events as `event.interaction.id`; text arrives on `step.delta` events where
  `event.delta.type == "text"` via `event.delta.text`.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

import auth
import db
from models import MessageCreate

# Request timeout for a single interaction turn (seconds).
_TURN_TIMEOUT = 900


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_text_delta(event: Any) -> str | None:
    """Return text from a step.delta event, or None if not a text delta."""
    delta = getattr(event, "delta", None)
    if delta is None:
        return None
    if getattr(delta, "type", None) == "text":
        return getattr(delta, "text", None)
    return None


def _stream_turn(conv: dict, user_text: str, assistant_msg_id: str) -> Iterator[str]:
    """Generator that drives one interaction turn and yields SSE frames.

    Runs in a threadpool (Starlette iterates sync generators off the event
    loop), so the blocking SDK stream iteration does not stall the server.
    """
    agent = conv.get("agent")
    project = conv.get("project")
    client = auth.get_genai_client(project)

    create_kwargs: dict[str, Any] = {
        "input": user_text,
        "stream": True,
        "store": True,
        "timeout": _TURN_TIMEOUT,
    }
    prev = conv.get("last_interaction_id")
    if prev:
        create_kwargs["previous_interaction_id"] = prev

    if agent:
        # Custom agent: background execution is required.
        create_kwargs["agent"] = agent
        create_kwargs["background"] = True
    else:
        # Base model (only where supported by the project).
        create_kwargs["model"] = conv.get("model")

    accumulated = ""
    interaction_id: str | None = None

    try:
        stream = client.interactions.create(**create_kwargs)
        for event in stream:
            event_type = getattr(event, "event_type", None)

            if event_type in ("interaction.created", "interaction.completed"):
                inter = getattr(event, "interaction", None)
                if inter is not None:
                    iid = getattr(inter, "id", None)
                    if iid:
                        interaction_id = iid

            elif event_type == "step.delta":
                text = _extract_text_delta(event)
                if text:
                    accumulated += text
                    yield _sse("delta", {"text": text})

            elif event_type == "error":
                err = getattr(event, "error", None)
                message = getattr(err, "message", None) or str(err)
                raise RuntimeError(message)

    except Exception as exc:  # noqa: BLE001 - surface any failure to the client
        db.update_message(
            assistant_msg_id,
            content=accumulated,
            status="error",
        )
        yield _sse("error", {"message": str(exc), "message_id": assistant_msg_id})
        return

    # Persist the completed assistant turn and advance the conversation state.
    db.update_message(
        assistant_msg_id,
        content=accumulated,
        interaction_id=interaction_id,
        status="complete",
    )
    if interaction_id:
        db.touch_conversation(conv["id"], last_interaction_id=interaction_id)
    else:
        db.touch_conversation(conv["id"])

    yield _sse(
        "done",
        {"message_id": assistant_msg_id, "interaction_id": interaction_id},
    )


def register_message_routes(app: FastAPI) -> None:
    @app.post("/api/conversations/{conv_id}/messages")
    def send_message(conv_id: str, body: MessageCreate) -> StreamingResponse:
        conv = db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Persist the user message, then create an empty assistant placeholder
        # so the client has a stable id to stream into.
        db.add_message(
            conversation_id=conv_id, role="user", content=body.content
        )
        assistant = db.add_message(
            conversation_id=conv_id,
            role="assistant",
            content="",
            status="streaming",
        )

        # Auto-title the conversation from the first user message.
        if conv["title"] in ("New chat", "", None):
            title = body.content.strip().splitlines()[0][:60] or "New chat"
            db.rename_conversation(conv_id, title)

        # Re-read to pick up last_interaction_id etc.
        conv = db.get_conversation(conv_id)
        assert conv is not None

        generator = _stream_turn(conv, body.content, assistant["id"])
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
