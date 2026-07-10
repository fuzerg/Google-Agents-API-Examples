# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""End-user OAuth 2.0 helper for the Google Workspace remote MCP servers.

The Google-hosted Workspace MCP servers (Gmail, Drive, Calendar, People, Chat)
act on behalf of a signed-in user and expect a standard Google OAuth 2.0 access
token in the ``Authorization: Bearer <token>`` header. This module mints such a
token with an installed-app (loopback) OAuth flow, caches the resulting refresh
token locally, and transparently refreshes the access token on later runs.

This is intentionally separate from Application Default Credentials (ADC): ADC
authenticates *your* call to the Interactions API, while this token authorizes
the *end user's* Workspace data that the MCP servers read and act on.
"""

from __future__ import annotations

import os
from typing import List, Optional, cast

import requests

# Relax scope validation: Google frequently returns a slightly different scope
# set than requested (e.g. it echoes back `openid`), which otherwise makes
# oauthlib raise. This must be set before importing the flow.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.transport.requests import Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def _scopes_cover(granted: Optional[List[str]], requested: List[str]) -> bool:
    """Return True if every requested scope is present in `granted`."""
    if not granted:
        return False
    granted_set = set(granted)
    return all(scope in granted_set for scope in requested)


def get_workspace_credentials(
    scopes: List[str],
    client_secret_file: str,
    token_file: str,
    login_hint: Optional[str] = None,
    force_reauth: bool = False,
    open_browser: bool = True,
) -> Credentials:
    """Return valid user credentials with `scopes`, running consent if needed.

    Args:
        scopes: OAuth scopes to request (must match your consent screen).
        client_secret_file: Path to the OAuth client `client_secret.json`
            (create a "Desktop app" OAuth client in your Google Cloud project).
        token_file: Path where the refresh/access token is cached as JSON.
        login_hint: Optional email to pre-select in the consent screen.
        force_reauth: Ignore the cached token and force a new consent flow.
        open_browser: Open a browser automatically for the consent flow.

    Returns:
        A `google.oauth2.credentials.Credentials` with a fresh access token.
    """
    creds: Optional[Credentials] = None

    if not force_reauth and os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, scopes)
        except Exception:
            creds = None
        # If the cached token was granted a narrower scope set than we now need,
        # discard it so we re-consent for the new scopes.
        if creds is not None and not _scopes_cover(creds.scopes, scopes):
            creds = None

    if creds is not None and creds.valid:
        return creds

    if creds is not None and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds, token_file)
            return creds
        except Exception:
            creds = None  # Fall through to a fresh consent flow.

    # No usable cached credentials — run the interactive installed-app flow.
    if not os.path.exists(client_secret_file):
        raise FileNotFoundError(
            f"OAuth client secret not found at '{client_secret_file}'.\n"
            "Create a 'Desktop app' OAuth 2.0 Client ID in the Google Cloud "
            "Console (APIs & Services > Credentials), download it, and save it "
            "there (or point --client-secret / GOOGLE_OAUTH_CLIENT_SECRET_FILE "
            "at it). See README.md for details."
        )

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, scopes)
    kwargs = {"open_browser": open_browser, "prompt": "consent"}
    if login_hint:
        kwargs["login_hint"] = login_hint
    creds = cast(Credentials, flow.run_local_server(port=0, **kwargs))
    _save(creds, token_file)
    return creds


def _save(creds: Credentials, token_file: str) -> None:
    with open(token_file, "w") as f:
        f.write(creds.to_json())
    try:
        os.chmod(token_file, 0o600)
    except OSError:
        pass


def introspect_token(access_token: str) -> dict:
    """Return Google's tokeninfo for an access token (email, scopes, expiry).

    Best-effort: returns an empty dict on failure.
    """
    try:
        resp = requests.get(
            TOKENINFO_URL, params={"access_token": access_token}, timeout=15
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return {}
