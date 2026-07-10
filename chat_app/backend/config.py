"""Application configuration resolved from environment variables.

All settings can be overridden via environment variables. Sensible defaults are
provided so the app runs locally with just Application Default Credentials.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Directory of this backend package.
BACKEND_DIR = Path(__file__).resolve().parent
# Repo-local data dir for the SQLite database.
DATA_DIR = BACKEND_DIR / "data"


class Settings:
    """Runtime settings for the chat app backend."""

    def __init__(self) -> None:
        # GCP project + location. Project may be resolved from ADC at runtime if
        # not set explicitly here.
        self.project_id: str | None = (
            os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCP_PROJECT")
            or None
        )
        self.location: str = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

        # Default base model used when a conversation is not bound to a custom
        # agent. Must be a current model (legacy 2.0/1.5 are unsupported).
        self.default_model: str = os.environ.get(
            "CHAT_APP_DEFAULT_MODEL", "gemini-3-flash-preview"
        )

        # Comma-separated list of base models offered in the UI picker.
        # NOTE: many projects only support interactions via custom agents (raw
        # base models return "Unsupported model interaction"), so this is empty
        # by default. Set CHAT_APP_BASE_MODELS to opt in where supported.
        self.base_models: list[str] = [
            m.strip()
            for m in os.environ.get("CHAT_APP_BASE_MODELS", "").split(",")
            if m.strip()
        ]

        # SQLite database path.
        self.db_path: str = os.environ.get(
            "CHAT_APP_DB_PATH", str(DATA_DIR / "chat.db")
        )

        # CORS origins for the Vite dev server.
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.environ.get(
                "CHAT_APP_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if o.strip()
        ]

    def aiplatform_base_url(self, project: str) -> str:
        """Base URL for the Control Plane (Managed Agents) REST API.

        The project is explicit so the UI can list agents from any project the
        caller has access to.
        """
        return (
            "https://aiplatform.googleapis.com/v1beta1/"
            f"projects/{project}/locations/{self.location}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
