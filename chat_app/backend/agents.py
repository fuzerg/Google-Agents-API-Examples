"""Control Plane (Managed Agents API) access: list existing agents.

Also exposes optional base models as selectable targets. Note that many
projects only support interactions through custom agents.
"""
from __future__ import annotations

import requests

from auth import get_access_token, get_default_project_id
from config import get_settings

_TIMEOUT = 30


def list_agents(project: str | None = None) -> dict:
    """List selectable targets for a project.

    Returns a dict: {"project": str, "agents": [target...], "error": str|None}.
    Custom agents are fetched from the Control Plane for the given project
    (defaults to the resolved default project).
    """
    settings = get_settings()
    project = project or get_default_project_id()
    targets: list[dict] = []
    error: str | None = None

    # Optional base model options (usually unsupported for interactions).
    for model in settings.base_models:
        targets.append(
            {
                "name": None,
                "display_name": f"{model} (base model)",
                "description": "Chat directly with a base model.",
                "kind": "model",
                "model": model,
                "project": project,
            }
        )

    # Custom agents from the Control Plane.
    try:
        token = get_access_token()
        resp = requests.get(
            f"{settings.aiplatform_base_url(project)}/agents",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            for agent in data.get("agents", []):
                resource_name = agent.get("name")
                if not resource_name:
                    continue
                short = resource_name.split("/")[-1]
                if not short:
                    # Skip malformed entries with an empty agent id.
                    continue
                targets.append(
                    {
                        "name": resource_name,
                        "display_name": short,
                        "description": agent.get("description"),
                        "kind": "agent",
                        "model": agent.get("base_agent"),
                        "project": project,
                    }
                )
        else:
            try:
                error = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                error = f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.RequestException as exc:
        error = str(exc)

    return {"project": project, "agents": targets, "error": error}
