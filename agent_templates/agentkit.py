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
"""Shared toolkit for the agent-template runners (`prober.py`, `chat.py`).

This module holds the code both runners need so it lives in exactly one place:

  * ADC auth + GCP project resolution
  * Enterprise Gen AI client initialization (Interactions API)
  * agent.yaml / AGENTS.md loading
  * Control Plane: register / delete a custom agent (with LRO polling)
  * Data Plane: run a streaming (or synchronous) interaction, with pluggable
    renderers (`SimpleRenderer` for plain runners, `RichRenderer` for chat)
  * Generic MCP helpers: build an Authorization header from an `auth` block,
    turn `mcp_servers` into tool specs, and a raw MCP connectivity preflight

The two entrypoints stay thin and keep only their unique behavior:
`prober.py` (GCS/skills, x-* extensions, single-turn examples) and `chat.py`
(interactive multi-turn chat against a given / template-provisioned agent).

NOTE: Use the unified Google Gen AI SDK (`google-genai >= 2.0.0`). Legacy SDKs
(`google-cloud-aiplatform`, `google-generativeai`) do NOT support interactions.
Use current models only (`gemini-2.5-pro`, `gemini-3-flash-preview`, ...);
`gemini-2.0`/`1.5` are unsupported.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests

LOCATION = "global"
MCP_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_BASE_AGENT = "antigravity-preview-05-2026"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


# ---------------------------------------------------------------------------
# ANSI helpers (no external deps).
# ---------------------------------------------------------------------------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"


def c(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C.RESET}"


def info(msg: str) -> None:
    print(c(msg, C.CYAN))


def ok(msg: str) -> None:
    print(c("\u2713 " + msg, C.GREEN))


def warn(msg: str) -> None:
    print(c("! " + msg, C.YELLOW))


def err(msg: str) -> None:
    print(c("\u2717 " + msg, C.RED))


def rule(title: str = "") -> None:
    line = "-" * 80
    if title:
        print(f"\n{c(line, C.DIM)}\n{c(title, C.BOLD)}\n{c(line, C.DIM)}")
    else:
        print(c(line, C.DIM))


# ---------------------------------------------------------------------------
# Auth + client.
# ---------------------------------------------------------------------------
def resolve_adc(scopes: Tuple[str, ...] = (CLOUD_PLATFORM_SCOPE,)):
    """Return (credentials, project_id) from Application Default Credentials."""
    import google.auth

    credentials, project_id = google.auth.default(scopes=list(scopes))
    return credentials, project_id


def access_token(credentials) -> str:
    """Refresh and return an access token string for the given ADC credentials."""
    from google.auth.transport.requests import Request

    credentials.refresh(Request())
    return credentials.token


def control_plane_token() -> str:
    """Convenience: a fresh cloud-platform access token for Control Plane REST."""
    credentials, _ = resolve_adc()
    return access_token(credentials)


def resolve_project(project: Optional[str] = None) -> str:
    """Resolve the GCP project from arg > env > ADC."""
    if project:
        return project
    env = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if env:
        return env
    _, adc_project = resolve_adc()
    if not adc_project:
        raise RuntimeError(
            "Could not resolve a GCP project. Pass --project, set "
            "GOOGLE_CLOUD_PROJECT, or run `gcloud config set project <ID>`."
        )
    return adc_project


def init_genai_client(project: Optional[str] = None, location: str = LOCATION):
    """Initialize the enterprise Gen AI client. Returns (client, project_id)."""
    from google import genai

    project_id = resolve_project(project)
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"
    client = genai.Client(enterprise=True, project=project_id, location=location)
    return client, project_id


# ---------------------------------------------------------------------------
# Config loading.
# ---------------------------------------------------------------------------
def load_config(path: str, expandvars: bool = False) -> Dict[str, Any]:
    import yaml

    with open(path, "r") as f:
        raw = f.read()
    if expandvars:
        raw = os.path.expandvars(raw)
    return yaml.safe_load(raw) or {}


def load_system_instruction(template_dir: str) -> Optional[str]:
    """Prefer AGENTS.md in the template directory as the system instruction."""
    agents_md = os.path.join(template_dir, "AGENTS.md")
    if os.path.exists(agents_md):
        with open(agents_md, "r") as f:
            return f.read()
    return None


def load_dotenv(path: str, override: bool = False) -> int:
    """Load KEY=VALUE lines from a `.env` file into os.environ.

    Simple, dependency-free parser: skips blank lines and `#` comments, tolerates
    a leading `export `, and strips surrounding single/double quotes. By default
    it does NOT override variables already set in the environment (the shell
    wins). Returns the number of variables applied. No-op if the file is missing.
    """
    if not path or not os.path.exists(path):
        return 0
    applied = 0
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value
                applied += 1
    if applied:
        info(f"Loaded {applied} var(s) from {path}")
    return applied


# ---------------------------------------------------------------------------
# Generic MCP helpers.
# ---------------------------------------------------------------------------
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
# ${base64:VAR1[:VAR2[:...]]} -> base64 of the colon-joined env values.
# This produces standard HTTP Basic credentials, e.g.
#   Authorization: "Basic ${base64:EMAIL_ENV:TOKEN_ENV}"
_B64_REF = re.compile(r"\$\{base64:([A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z_][A-Za-z0-9_]*)*)\}")


def _env(name: str) -> str:
    val = os.environ.get(name)
    if val is None:
        raise RuntimeError(f"Header value references unset env var: {name}")
    return val


def _interpolate_env(value: str) -> str:
    """Expand references in a header value.

    Supports:
      * `${VAR}` / `$VAR`            -> the env var's value
      * `${base64:VAR1:VAR2:...}`    -> base64(":".join(env values)); the standard
                                        HTTP Basic form is `${base64:USER:PASS}`
    Unset referenced env vars raise a clear error.
    """
    def b64repl(m: "re.Match[str]") -> str:
        joined = ":".join(_env(n) for n in m.group(1).split(":"))
        return base64.b64encode(joined.encode("utf-8")).decode("ascii")

    def envrepl(m: "re.Match[str]") -> str:
        return _env(m.group(1) or m.group(2))

    # base64 first (its output has no `$`, so it's safe from the second pass).
    value = _B64_REF.sub(b64repl, value)
    return _ENV_REF.sub(envrepl, value)


def build_auth_headers(auth_cfg: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Build the HTTP headers for a single MCP server from its `auth` block.

    Auth is declared per MCP server in agent.yaml as a raw `headers` map whose
    values reference env vars (no credential values are hardcoded). Header values
    support `${VAR}` / `$VAR` and a `${base64:...}` transform for HTTP Basic. This
    maps directly onto the `mcp_server` tool's `headers` field:

      mcp_servers:
        - name: my-server
          url: https://...
          auth:
            headers:
              # HTTP Basic (base64 of "email:token") — drop in the two env vars:
              Authorization: "Basic ${base64:MY_EMAIL:MY_TOKEN}"
              # or Bearer:   Authorization: "Bearer ${MY_API_KEY}"
              # or any custom header:
              X-API-Key: "${MY_API_KEY}"

    Returns None when the server has no `auth` block (or it declares no headers).
    A referenced env var that is unset raises a clear error.
    """
    if not auth_cfg:
        return None
    raw_headers = auth_cfg.get("headers")
    if raw_headers is None:
        return None
    if not isinstance(raw_headers, dict):
        raise RuntimeError("`auth.headers` must be a mapping of header name -> value.")
    headers: Dict[str, str] = {}
    for name, value in raw_headers.items():
        headers[str(name)] = _interpolate_env(str(value))
    if headers:
        info(f"Auth: header(s) {', '.join(sorted(headers))}")
    return headers or None


def resolve_servers(
    config: Dict[str, Any],
    servers_filter: Optional[List[str]] = None,
    url_override: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the selected MCP servers as {name, url, auth} dicts.

    Each server's per-server `auth` block (if any) is carried through so callers
    can build a distinct Authorization header per server.
    """
    selected = []
    for s in config.get("mcp_servers", []) or []:
        name = s.get("name")
        url = url_override or s.get("url")
        if not name or not url:
            continue
        if servers_filter is not None and name not in servers_filter:
            continue
        if servers_filter is None and not s.get("enabled", True):
            continue
        selected.append({"name": name, "url": url, "auth": s.get("auth")})
    return selected


def build_mcp_tools(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn a server list into `mcp_server` tool specs, one header set per server.

    Each server carries its own `auth` block, so a distinct set of headers is
    built per server (see build_auth_headers). The same `mcp_server` tool shape
    is accepted both baked into the agent (Control Plane) and per interaction
    (Data Plane); the Control Plane rejects the older `mcp` type, so use
    `mcp_server`.
    """
    tools = []
    for s in servers:
        tool: Dict[str, Any] = {
            "type": "mcp_server",
            "name": s["name"],
            "url": s["url"],
        }
        headers = build_auth_headers(s.get("auth"))
        if headers:
            tool["headers"] = headers
        tools.append(tool)
    return tools


# ---------------------------------------------------------------------------
# Raw MCP connectivity preflight (streamable HTTP JSON-RPC).
# ---------------------------------------------------------------------------
def _parse_mcp_body(resp: requests.Response) -> Optional[dict]:
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        last = None
        for line in resp.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                    last = obj
        return last
    try:
        return resp.json()
    except ValueError:
        return None


def _mcp_post(session, url, auth_headers, payload, session_id, timeout):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if auth_headers:
        headers.update(auth_headers)
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return session.post(url, headers=headers, json=payload, timeout=timeout)


def mcp_list_tools(
    url: str, auth_headers: Optional[Dict[str, str]], timeout: int = 30
) -> Tuple[bool, List[str], str]:
    """Directly initialize + list tools on a remote MCP server.

    `auth_headers` is a header-name -> value map (see build_auth_headers).
    Returns (ok, tool_names, error_message).
    """
    session = requests.Session()
    try:
        init = _mcp_post(
            session, url, auth_headers,
            {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "agentkit", "version": "1.0.0"},
                },
            },
            session_id=None, timeout=timeout,
        )
        if init.status_code in (401, 403):
            return False, [], f"HTTP {init.status_code} (auth/scope): {init.text[:200]}"
        if init.status_code >= 400:
            return False, [], f"HTTP {init.status_code}: {init.text[:200]}"

        session_id = init.headers.get("Mcp-Session-Id") or init.headers.get(
            "mcp-session-id"
        )
        try:
            _mcp_post(
                session, url, auth_headers,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                session_id=session_id, timeout=timeout,
            )
        except requests.RequestException:
            pass

        listing = _mcp_post(
            session, url, auth_headers,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_id=session_id, timeout=timeout,
        )
        body = _parse_mcp_body(listing)
        if body and isinstance(body.get("result"), dict):
            tools = body["result"].get("tools")
            if tools is not None:
                names = [t.get("name", "?") for t in tools]
                if listing.status_code >= 400:
                    return True, names, (
                        f"(HTTP {listing.status_code} at tools/list; execution "
                        "may still require a valid token/scopes)"
                    )
                return True, names, ""
        if listing.status_code >= 400:
            return False, [], f"tools/list HTTP {listing.status_code}: {listing.text[:200]}"
        if not body:
            return False, [], "Could not parse tools/list response."
        if "error" in body:
            return False, [], f"tools/list error: {body['error']}"
        return True, [], ""
    except requests.RequestException as e:
        return False, [], f"request failed: {e}"


def preflight_mcp(servers: List[Dict[str, Any]]) -> bool:
    """Run mcp_list_tools against each server (with its own auth), printing a report."""
    rule("MCP server connectivity preflight")
    all_ok = True
    for s in servers:
        name, url = s["name"], s["url"]
        good, tools, error = mcp_list_tools(url, build_auth_headers(s.get("auth")))
        if good:
            ok(f"{name:9s} {url}")
            print(c(f"    tools ({len(tools)}): " + ", ".join(tools), C.DIM))
            if error:
                print(c(f"    note: {error}", C.YELLOW))
        else:
            all_ok = False
            err(f"{name:9s} {url}")
            print(c(f"    {error}", C.DIM))
    return all_ok


# ---------------------------------------------------------------------------
# Control Plane: register / delete agents.
# ---------------------------------------------------------------------------
def default_base_environment(
    env_config: Optional[Dict[str, Any]] = None, allow_network: bool = False
) -> Dict[str, Any]:
    """Build a `base_environment` payload.

    Uses `env_config` (agent.yaml `environment`) when provided. Falls back to a
    remote environment; if `allow_network` (e.g. the agent uses remote MCP tools)
    and no explicit network is configured, an outbound allowlist is added.
    """
    env_config = env_config or {}
    base_env: Dict[str, Any] = {
        "type": env_config.get("type", "remote"),
        "sources": env_config.get("sources", []),
    }
    if "network" in env_config:
        base_env["network"] = env_config["network"]
    elif allow_network:
        base_env["network"] = {"allowlist": [{"domain": "*"}]}
    return base_env


def register_agent(
    project: str,
    token: str,
    agent_id: str,
    base_agent: str,
    description: str,
    *,
    system_instruction: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    base_environment: Optional[Dict[str, Any]] = None,
    location: str = LOCATION,
    poll_timeout: int = 180,
) -> str:
    """Register a custom agent via the Control Plane and wait until ready.

    Returns the full agent resource name. If `tools` is provided they are baked
    into the agent (self-contained), so a thin client can later call it with just
    {agent, input}. Reuses an existing agent on HTTP 409.
    """
    import time

    base = f"https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{location}"
    resource = f"projects/{project}/locations/{location}/agents/{agent_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload: Dict[str, Any] = {
        "id": agent_id,
        "base_agent": base_agent,
        "description": description,
        "base_environment": base_environment or default_base_environment(),
    }
    if system_instruction:
        payload["system_instruction"] = system_instruction
    if tools:
        payload["tools"] = tools

    resp = requests.post(f"{base}/agents", headers=headers, json=payload, timeout=60)
    if resp.status_code not in (200, 409):
        raise RuntimeError(f"Failed to create agent: HTTP {resp.status_code} {resp.text}")
    if resp.status_code == 409:
        return resource

    operation_name = resp.json().get("name")
    if operation_name:
        deadline = time.time() + poll_timeout
        while time.time() < deadline:
            poll = requests.get(
                f"https://aiplatform.googleapis.com/v1beta1/{operation_name}",
                headers=headers, timeout=60,
            )
            data = poll.json()
            if data.get("done"):
                if "error" in data:
                    raise RuntimeError(f"Agent registration failed: {data['error']}")
                break
            time.sleep(3)
    return resource


def delete_agent(project: str, token: str, agent_id: str, location: str = LOCATION) -> None:
    """Best-effort delete of an agent."""
    url = (
        f"https://aiplatform.googleapis.com/v1beta1/projects/{project}"
        f"/locations/{location}/agents/{agent_id}"
    )
    try:
        requests.delete(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    except requests.RequestException:
        pass


def agent_resource_name(agent: str, project: str, location: str = LOCATION) -> str:
    """Accept either a bare agent id or a full resource name and return the full name."""
    if agent.startswith("projects/"):
        return agent
    return f"projects/{project}/locations/{location}/agents/{agent}"


# ---------------------------------------------------------------------------
# Data Plane: streaming interactions + renderers.
# ---------------------------------------------------------------------------
class SimpleRenderer:
    """Plain renderer: prints text and code-execution results inline."""
    
    def __init__(self) -> None:
        self.text_buffer = ""

    def handle_event(self, event: Any) -> None:
        if getattr(event, "event_type", None) != "step.delta":
            return
        delta = getattr(event, "delta", None)
        if delta is None:
            return
        dtype = getattr(delta, "type", None)
        if dtype == "text":
            text = getattr(delta, "text", "") or ""
            if text:
                print(text, end="", flush=True)
                self.text_buffer += text
        elif dtype == "tool_call":
            name = getattr(delta, "name", "?")
            args = getattr(delta, "arguments", {})
            print(f"\n--> Executing Tool: {name} with args: {args}\n", flush=True)
        elif dtype == "code_execution_result":
            result = getattr(delta, "result", "") or ""
            if result:
                print(result, end="", flush=True)

    def finish(self) -> None:
        print()


class RichRenderer:
    """Colored renderer that also surfaces thoughts and MCP tool-call events."""

    def __init__(self) -> None:
        self._in_text = False

    def _break_text(self) -> None:
        if self._in_text:
            print()
            self._in_text = False

    def handle_event(self, event: Any) -> None:
        if getattr(event, "event_type", None) != "step.delta":
            return
        delta = getattr(event, "delta", None)
        if delta is None:
            return
        dtype = getattr(delta, "type", None)
        print(f"\n[DEBUG DELTA] {dtype}: {delta}\n", flush=True)
        if dtype == "text":
            text = getattr(delta, "text", "") or ""
            if text:
                print(text, end="", flush=True)
                self._in_text = True
        elif dtype == "thought_summary":
            thought = getattr(delta, "text", "") or getattr(delta, "summary", "")
            if thought:
                self._break_text()
                print(c(f"  [thinking] {thought}", C.DIM))
        elif dtype == "mcp_server_tool_call":
            self._break_text()
            server = getattr(delta, "server_name", "?")
            name = getattr(delta, "name", "?")
            args = getattr(delta, "arguments", {})
            args_str = json.dumps(args, ensure_ascii=False) if args else "{}"
            if len(args_str) > 200:
                args_str = args_str[:200] + "..."
            print(c(f"  \u2192 tool call [{server}.{name}] {args_str}", C.BLUE))
        elif dtype == "mcp_server_tool_result":
            self._break_text()
            print(c("  \u2190 tool result received", C.BLUE))
        elif dtype == "tool_call":
            name = getattr(delta, "name", "?")
            args = getattr(delta, "arguments", {})
            print(f"\n--> Executing Tool: {name} with args: {args}\n", flush=True)
        elif dtype == "code_execution_result":
            result = getattr(delta, "result", "") or ""
            if result:
                self._break_text()
                print(c(f"  [code result] {result}", C.DIM))

    def finish(self) -> None:
        self._break_text()


def extract_final_text(interaction: Any) -> str:
    """Pull the final model text out of a completed interaction object."""
    steps = getattr(interaction, "steps", None) or []
    for step in reversed(steps):
        content = getattr(step, "content", None) or []
        texts: List[str] = []
        for part in content:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)
        if texts:
            return "".join(texts)
    return ""


def stream_interaction(
    client: Any,
    agent_resource: str,
    prompt: str,
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    previous_interaction_id: Optional[str] = None,
    environment: Optional[Dict[str, Any]] = None,
    stream: bool = True,
    background: bool = True,
    store: bool = True,
    timeout: int = 3600,
    renderer: Optional[Any] = None,
) -> Tuple[str, Optional[str]]:
    """Run one interaction turn. Returns (final_text, interaction_id).

    `tools` is omitted when empty (a thin turn against a self-contained agent).
    In streaming mode, text deltas are accumulated for `final_text` and the
    interaction id is captured from lifecycle events for multi-turn chaining.
    """
    kwargs: Dict[str, Any] = {"agent": agent_resource, "input": prompt, "store": store}
    if tools:
        kwargs["tools"] = tools
    if previous_interaction_id:
        kwargs["previous_interaction_id"] = previous_interaction_id
    if environment:
        kwargs["environment"] = environment

    if not stream:
        interaction = client.interactions.create(**kwargs)
        final_text = extract_final_text(interaction)
        print(final_text)
        return final_text, getattr(interaction, "id", None)

    active_renderer = renderer if renderer is not None else SimpleRenderer()
    final_text = ""
    interaction_id = None
    response_stream = client.interactions.create(
        stream=True, background=background, timeout=timeout, **kwargs
    )
    for event in response_stream:
        active_renderer.handle_event(event)
        # Accumulate text for callers that need the transcript (e.g. prober's
        # x-extract-messages), independent of how the renderer displays it.
        if getattr(event, "event_type", None) == "step.delta":
            delta = getattr(event, "delta", None)
            if delta is not None and getattr(delta, "type", None) == "text":
                final_text += getattr(delta, "text", "") or ""
        # Capture the interaction id for stateful multi-turn chaining.
        inter = getattr(event, "interaction", None)
        iid = (
            getattr(inter, "id", None)
            or getattr(event, "interaction_id", None)
            or getattr(event, "id", None)
        )
        if iid:
            interaction_id = iid
    active_renderer.finish()
    return final_text, interaction_id


def package_dir() -> str:
    """Absolute path to the directory containing this module (agent_templates/)."""
    return os.path.dirname(os.path.abspath(__file__))
