"""Application Default Credentials (ADC) and google-genai client management.

Mirrors the auth pattern used in agent_templates/prober.py: resolve ADC credentials,
refresh access tokens on demand for Control Plane REST calls, and construct an
enterprise google-genai client for the Interactions API (Data Plane).
"""
from __future__ import annotations

import threading

import google.auth
import google.auth.transport.requests
from google import genai

from config import get_settings

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

_lock = threading.Lock()
_credentials = None
_auth_request = None
_genai_clients: dict[str, genai.Client] = {}
_resolved_project: str | None = None


class AuthError(RuntimeError):
    """Raised when ADC credentials cannot be resolved."""


def _ensure_credentials():
    """Resolve ADC credentials + project once, caching them."""
    global _credentials, _auth_request, _resolved_project
    if _credentials is not None:
        return
    try:
        credentials, project_id = google.auth.default(scopes=_SCOPES)
    except Exception as exc:  # noqa: BLE001 - surface a friendly message
        raise AuthError(
            "Could not resolve Application Default Credentials. "
            "Run: gcloud auth application-default login"
        ) from exc

    settings = get_settings()
    _resolved_project = settings.project_id or project_id
    if not _resolved_project:
        raise AuthError(
            "No GCP project resolved. Set GOOGLE_CLOUD_PROJECT or run: "
            "gcloud config set project <PROJECT_ID>"
        )
    _credentials = credentials
    _auth_request = google.auth.transport.requests.Request()


def get_default_project_id() -> str:
    """Return the default GCP project id resolved from env/ADC."""
    with _lock:
        _ensure_credentials()
        assert _resolved_project is not None
        return _resolved_project


def get_access_token() -> str:
    """Return a valid access token, refreshing if necessary."""
    with _lock:
        _ensure_credentials()
        assert _credentials is not None and _auth_request is not None
        if not _credentials.valid:
            _credentials.refresh(_auth_request)
        elif _credentials.expired:
            _credentials.refresh(_auth_request)
        # google-auth marks freshly-loaded creds as invalid until first refresh.
        if _credentials.token is None:
            _credentials.refresh(_auth_request)
        return _credentials.token


def get_genai_client(project: str | None = None) -> genai.Client:
    """Return a cached enterprise google-genai client for the given project.

    Clients are cached per project so the UI can talk to agents in any project
    the caller can access. Defaults to the resolved default project.
    """
    with _lock:
        _ensure_credentials()
        settings = get_settings()
        proj = project or _resolved_project
        assert proj is not None
        client = _genai_clients.get(proj)
        if client is None:
            client = genai.Client(
                enterprise=True,
                project=proj,
                location=settings.location,
            )
            _genai_clients[proj] = client
        return client


def health() -> dict:
    """Return an auth/project health snapshot for the UI."""
    try:
        project = get_default_project_id()
        # Force a token acquisition to confirm ADC works.
        token_ok = bool(get_access_token())
        return {
            "authenticated": token_ok,
            "project_id": project,
            "location": get_settings().location,
        }
    except AuthError as exc:
        return {
            "authenticated": False,
            "project_id": None,
            "location": get_settings().location,
            "error": str(exc),
        }
