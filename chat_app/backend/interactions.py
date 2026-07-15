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


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort convert a Pydantic event/step/delta model to a plain dict."""
    if obj is None:
        return {}
    try:
        return obj.model_dump(mode="json")
    except Exception:  # noqa: BLE001 - fall back for non-standard models
        try:
            return obj.model_dump()
        except Exception:  # noqa: BLE001
            return {}


def _coerce_json(val: Any) -> Any:
    """Parse JSON-encoded strings (and the common ``{"result": "<json>"}``
    wrapper the API uses for tool results) into structured data so the client
    can render it cleanly instead of an escaped string blob."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:  # noqa: BLE001 - not JSON, keep the raw string
            return val
    if (
        isinstance(val, dict)
        and list(val.keys()) == ["result"]
        and isinstance(val["result"], str)
    ):
        try:
            return json.loads(val["result"])
        except Exception:  # noqa: BLE001
            return val["result"]
    return val


def _truncate_for_display(val: Any, limit: int = 2000) -> Any:
    """Cap very large payloads (e.g. a full search result) so the intermediate
    events console stays readable."""
    s = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    if len(s) > limit:
        return s[:limit] + f"… [truncated {len(s) - limit} chars]"
    return val


def _finalize_step(step: dict[str, Any]) -> dict[str, Any] | None:
    """Build a consolidated agent_event payload for a completed step.

    Returns None for steps that carry nothing worth surfacing (e.g. the
    ``model_output`` text step, which is already streamed into the message),
    so the console never shows empty args/results rows.
    """
    stype = step.get("type")
    data: dict[str, Any] = {}
    if stype:
        data["type"] = stype
    if step.get("name"):
        data["name"] = step["name"]

    args_buf = step.get("args_buf") or ""
    if args_buf:
        try:
            data["arguments"] = json.loads(args_buf)
        except Exception:  # noqa: BLE001 - partial/non-JSON args, show raw
            data["arguments"] = args_buf

    if step.get("result") is not None:
        data["result"] = _truncate_for_display(_coerce_json(step["result"]))
        if step.get("is_error") is not None:
            data["is_error"] = step["is_error"]

    extra = step.get("extra")
    if extra:
        data["details"] = _truncate_for_display(extra)

    # Skip steps with nothing worth showing (e.g. the model_output text step,
    # already streamed into the message). A named tool call/result is kept even
    # with empty args so the agent's action trace stays complete — but we never
    # emit an empty ``arguments: {}`` / ``result: {}`` row.
    if not step.get("name") and not any(
        k in data for k in ("arguments", "result", "details")
    ):
        return None

    return {"event_type": stype or "step", "data": data}


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
    # Per-step accumulator (keyed by event index). Tool arguments and results
    # arrive incrementally on step.delta events; step.start/step.stop carry no
    # payload, so we assemble them here and emit one populated event per step.
    steps: dict[Any, dict[str, Any]] = {}

    try:
        stream = client.interactions.create(**create_kwargs)
        for event in stream:
            event_type = getattr(event, "event_type", None)

            if event_type in ("interaction.created", "interaction.completed"):
                inter = getattr(event, "interaction", None)
                iid = getattr(inter, "id", None) if inter is not None else None
                if iid:
                    interaction_id = iid
                yield _sse(
                    "agent_event",
                    {"event_type": event_type, "data": {"interaction_id": iid}},
                )

            elif event_type == "interaction.status_update":
                iid = getattr(event, "interaction_id", None)
                if iid:
                    interaction_id = iid
                yield _sse(
                    "agent_event",
                    {
                        "event_type": event_type,
                        "data": {
                            "status": getattr(event, "status", None),
                            "interaction_id": iid,
                        },
                    },
                )

            elif event_type == "step.start":
                idx = getattr(event, "index", None)
                sd = _model_to_dict(getattr(event, "step", None))
                steps[idx] = {
                    "type": sd.get("type"),
                    "name": sd.get("name"),
                    "id": sd.get("id") or sd.get("call_id"),
                    "args_buf": "",
                    "result": None,
                    "is_error": None,
                }

            elif event_type == "step.delta":
                idx = getattr(event, "index", None)
                dd = _model_to_dict(getattr(event, "delta", None))
                dtype = dd.get("type")
                if dtype == "text":
                    # The visible answer text: stream it into the message.
                    text = dd.get("text")
                    if text:
                        accumulated += text
                        yield _sse("delta", {"text": text})
                else:
                    st = steps.setdefault(
                        idx,
                        {
                            "type": None, "name": None, "id": None,
                            "args_buf": "", "result": None, "is_error": None,
                        },
                    )
                    if dtype == "arguments_delta":
                        st["args_buf"] += dd.get("arguments") or ""
                    elif dtype == "function_result":
                        res = dd.get("result")
                        if isinstance(res, str) and isinstance(st.get("result"), str):
                            st["result"] += res  # concatenate chunked string result
                        else:
                            st["result"] = res
                        st["is_error"] = dd.get("is_error")
                        if dd.get("name"):
                            st["name"] = dd["name"]
                    else:
                        # Other tool call/result deltas (search, code exec, …).
                        payload = {k: v for k, v in dd.items() if k != "type"}
                        if payload:
                            st.setdefault("extra", []).append(payload)

            elif event_type == "step.stop":
                idx = getattr(event, "index", None)
                st = steps.pop(idx, None)
                if st:
                    payload = _finalize_step(st)
                    if payload:
                        yield _sse("agent_event", payload)

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
