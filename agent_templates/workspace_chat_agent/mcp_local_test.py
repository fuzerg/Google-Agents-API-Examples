#!/usr/bin/env python3
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
"""Local, agent-free tester for the Google Workspace remote MCP servers.

This bypasses the Gemini Interactions API and the Agents Control Plane entirely.
It mints a user OAuth token directly (installed-app browser consent) using your
own OAuth client, optionally including the MCP **resource indicator**
(RFC 8707) that the MCP-native OAuth flow uses, then speaks raw MCP
(initialize -> tools/list -> tools/call) to a single Workspace MCP server.

Purpose: determine whether the Workspace MCP servers grant tool *execution* to a
token minted this way, isolating the MCP layer from the agent.

Usage:
  python3 mcp_local_test.py --server gmail
  python3 mcp_local_test.py --server people --tool get_user_profile
  python3 mcp_local_test.py --server gmail --no-resource   # omit resource indicator
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

import test_agent as t  # reuse the raw MCP helpers (_mcp_post, _parse_mcp_body)
import workspace_auth

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Per-server endpoint, the scopes that server needs, and a safe default read-only
# tool (with arguments) to exercise.
SERVERS = {
    "gmail": {
        "url": "https://gmailmcp.googleapis.com/mcp/v1",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        "tool": ("list_labels", {}),
    },
    "drive": {
        "url": "https://drivemcp.googleapis.com/mcp/v1",
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
        ],
        "tool": ("list_recent_files", {}),
    },
    "calendar": {
        "url": "https://calendarmcp.googleapis.com/mcp/v1",
        "scopes": [
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.freebusy",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ],
        "tool": ("list_calendars", {}),
    },
    "people": {
        "url": "https://people.googleapis.com/mcp/v1",
        "scopes": [
            "https://www.googleapis.com/auth/directory.readonly",
            "https://www.googleapis.com/auth/contacts.readonly",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        "tool": ("get_user_profile", {}),
    },
}


def mint_token(scopes, client_secret, token_file, resource, reauth, port=0):
    """Installed-app OAuth, optionally with an RFC 8707 resource indicator."""
    # We call the lower-level flow ourselves so we can inject `resource` into the
    # authorization request (workspace_auth.get_workspace_credentials doesn't).
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if not reauth and os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, scopes)
        except Exception:
            creds = None
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
    if creds and creds.valid:
        return creds.token

    if not os.path.exists(client_secret):
        raise FileNotFoundError(
            f"OAuth client secret not found at '{client_secret}'. Create a Desktop "
            "(or Web) OAuth client and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(client_secret, scopes)
    extra = {}
    if resource:
        # RFC 8707 resource indicator — bind the token to this MCP server.
        extra["resource"] = resource
    creds = flow.run_local_server(port=port, prompt="consent", open_browser=True, **extra)
    with open(token_file, "w") as f:
        f.write(creds.to_json())
    return creds.token


def mcp_call(url, token, method, params, session_id=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    resp = t._mcp_post(requests.Session(), url, token, payload, session_id, 60)
    return resp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--server", choices=sorted(SERVERS), default="gmail")
    ap.add_argument("--tool", help="Tool name to call (default: server's read-only tool).")
    ap.add_argument(
        "--no-resource",
        action="store_true",
        help="Do NOT include the RFC 8707 resource indicator in the OAuth request.",
    )
    ap.add_argument("--client-secret", default=os.path.join(SCRIPT_DIR, "client_secret.json"))
    ap.add_argument("--token", help="Token cache file (default per-server).")
    ap.add_argument("--reauth", action="store_true")
    ap.add_argument(
        "--port",
        type=int,
        default=0,
        help="Fixed loopback port for the OAuth redirect. Use with a Web-app "
        "client that has http://localhost:PORT/ registered as a redirect URI.",
    )
    args = ap.parse_args()

    spec = SERVERS[args.server]
    url = spec["url"]
    scopes = spec["scopes"]
    tool_name, tool_args = spec["tool"]
    if args.tool:
        tool_name = args.tool
        tool_args = {}
    resource = None if args.no_resource else url
    token_file = args.token or os.path.join(SCRIPT_DIR, f"token_local_{args.server}.json")

    print(f"Server:   {args.server}  ({url})")
    print(f"Scopes:   {[s.rsplit('/', 1)[-1] for s in scopes]}")
    print(f"Resource indicator: {resource or '(omitted)'}")

    try:
        token = mint_token(
            scopes, args.client_secret, token_file, resource, args.reauth, args.port
        )
    except Exception as e:  # noqa: BLE001
        print(f"Token mint failed: {e}")
        return 1
    if not token:
        print("Token mint returned no access token.")
        return 1

    info = workspace_auth.introspect_token(token)
    print(f"Authorized as: {info.get('email')}  aud={info.get('aud')}")

    # initialize
    init = mcp_call(url, token, "initialize", {
        "protocolVersion": t.MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "mcp-local-test", "version": "1.0.0"},
    })
    sid = init.headers.get("Mcp-Session-Id") or init.headers.get("mcp-session-id")
    print(f"initialize: HTTP {init.status_code}  session={'yes' if sid else 'no'}")

    mcp_call(url, token, "notifications/initialized", None, sid)

    # tools/call
    call = mcp_call(url, token, "tools/call", {"name": tool_name, "arguments": tool_args}, sid)
    body = t._parse_mcp_body(call) or {}
    result = body.get("result", {})
    print(f"\ntools/call {tool_name}: HTTP {call.status_code}  isError={result.get('isError')}")
    print(json.dumps(result, indent=2)[:1500])
    return 0 if result and not result.get("isError") else 2


if __name__ == "__main__":
    sys.exit(main())
