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
"""Standalone, multi-turn runner for the Atlassian Chat Agent.

This script exercises the agent end-to-end WITHOUT prober.py, using Atlassian's
official hosted remote Rovo MCP server (https://mcp.atlassian.com/v1/mcp):

  1. Builds an Atlassian `Authorization` header from an API token (Basic auth
     with a personal token, or Bearer with a service-account key).
  2. Resolves your Application Default Credentials (ADC) + project for the
     Interactions API (the Data Plane call to the Gemini Enterprise Agent
     Platform).
  3. Optionally connects directly to the Rovo MCP server and lists its tools, as
     a fast connectivity/auth preflight (`--check` / `--list-tools`).
  4. Registers a custom agent (Control Plane), then runs stateful, streaming
     Interactions where the model is given the Rovo MCP server as an
     `mcp_server` tool (Authorization header forwarded per turn), letting it
     read/search/act on Jira and Confluence. Cleans up the agent afterwards.

Usage:
  # One-time / preflight: verify the token + MCP connectivity, then exit.
  python3 chat.py --check

  # List the tools the Rovo MCP server exposes for your token.
  python3 chat.py --list-tools

  # Run all example prompts from agent.yaml.
  python3 chat.py

  # Run a single ad-hoc prompt.
  python3 chat.py "Summarize the open bugs in the PLATFORM project."

  # Interactive multi-turn chat (stateful).
  python3 chat.py --interactive

Credentials are read from the environment (see agent.yaml `auth`):
  Basic (personal token):  ATLASSIAN_EMAIL + ATLASSIAN_API_TOKEN
  Bearer (service key):    ATLASSIAN_API_KEY   (with --auth-mode bearer)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCATION = "global"
MCP_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_MCP_URL = "https://mcp.atlassian.com/v1/mcp"


# ---------------------------------------------------------------------------
# Small ANSI helpers (no external deps).
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


def _c(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C.RESET}"


def info(msg: str) -> None:
    print(_c(msg, C.CYAN))


def ok(msg: str) -> None:
    print(_c("\u2713 " + msg, C.GREEN))


def warn(msg: str) -> None:
    print(_c("! " + msg, C.YELLOW))


def err(msg: str) -> None:
    print(_c("\u2717 " + msg, C.RED))


def rule(title: str = "") -> None:
    line = "-" * 80
    if title:
        print(f"\n{_c(line, C.DIM)}\n{_c(title, C.BOLD)}\n{_c(line, C.DIM)}")
    else:
        print(_c(line, C.DIM))


def _mask(secret: str, keep: int = 4) -> str:
    if not secret:
        return "<empty>"
    if len(secret) <= keep:
        return "*" * len(secret)
    return secret[:keep] + "*" * (len(secret) - keep)


# ---------------------------------------------------------------------------
# Config loading.
# ---------------------------------------------------------------------------
def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}


def load_system_instruction() -> Optional[str]:
    agents_md = os.path.join(SCRIPT_DIR, "AGENTS.md")
    if os.path.exists(agents_md):
        with open(agents_md, "r") as f:
            return f.read()
    return None


def resolve_servers(
    config: Dict[str, Any], servers_filter: Optional[List[str]], url_override: Optional[str]
) -> List[Dict[str, str]]:
    """Return the list of {name,url} MCP servers to use."""
    all_servers = config.get("mcp_servers", []) or []
    if not all_servers:
        all_servers = [{"name": "atlassian", "url": DEFAULT_MCP_URL, "enabled": True}]
    selected = []
    for s in all_servers:
        name = s.get("name")
        url = url_override or s.get("url")
        if not name or not url:
            continue
        if servers_filter is not None:
            if name in servers_filter:
                selected.append({"name": name, "url": url})
        elif s.get("enabled", True):
            selected.append({"name": name, "url": url})
    return selected


# ---------------------------------------------------------------------------
# Atlassian API-token auth header.
# ---------------------------------------------------------------------------
def build_atlassian_auth_header(
    config: Dict[str, Any], args: argparse.Namespace
) -> str:
    """Build the `Authorization` header forwarded to the Rovo MCP server.

    Supports two non-interactive modes documented by Atlassian:
      basic  -> personal API token: `Basic base64(email:api_token)`
      bearer -> service-account API key: `Bearer <api_key>`
    """
    auth_cfg = config.get("auth", {}) or {}
    mode = (args.auth_mode or auth_cfg.get("mode", "basic")).lower()

    email_env = auth_cfg.get("email_env", "ATLASSIAN_EMAIL")
    token_env = auth_cfg.get("api_token_env", "ATLASSIAN_API_TOKEN")
    key_env = auth_cfg.get("api_key_env", "ATLASSIAN_API_KEY")

    if mode == "basic":
        email = args.email or os.environ.get(email_env)
        token = args.api_token or os.environ.get(token_env)
        if not email or not token:
            raise RuntimeError(
                "Basic auth needs an email + API token. Set "
                f"{email_env} and {token_env} (or pass --email / --api-token). "
                "Create a personal API token at "
                "https://id.atlassian.com/manage-profile/security/api-tokens"
            )
        raw = f"{email}:{token}".encode("utf-8")
        info(f"Auth: Basic (personal token) as {email} (token {_mask(token)})")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    if mode == "bearer":
        key = args.api_key or os.environ.get(key_env)
        if not key:
            raise RuntimeError(
                f"Bearer auth needs a service-account API key. Set {key_env} "
                "(or pass --api-key)."
            )
        info(f"Auth: Bearer (service-account key {_mask(key)})")
        return "Bearer " + key

    raise RuntimeError(f"Unknown auth mode '{mode}' (expected 'basic' or 'bearer').")


def build_mcp_tools(
    servers: List[Dict[str, str]], auth_header: str
) -> List[Dict[str, Any]]:
    """Turn the server list into Interactions API `mcp_server` tool specs."""
    tools = []
    for s in servers:
        tools.append(
            {
                "type": "mcp_server",
                "name": s["name"],
                "url": s["url"],
                "headers": {"Authorization": auth_header},
            }
        )
    return tools


# ---------------------------------------------------------------------------
# Raw MCP connectivity preflight (streamable HTTP JSON-RPC).
# ---------------------------------------------------------------------------
def _parse_mcp_body(resp: requests.Response) -> Optional[dict]:
    """Parse a streamable-HTTP MCP response (JSON or SSE) into a JSON-RPC obj."""
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


def _mcp_post(
    session: requests.Session,
    url: str,
    auth_header: str,
    payload: dict,
    session_id: Optional[str],
    timeout: int,
) -> requests.Response:
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return session.post(url, headers=headers, json=payload, timeout=timeout)


def mcp_list_tools(
    url: str, auth_header: str, timeout: int = 30
) -> Tuple[bool, List[str], str]:
    """Directly initialize + list tools on the remote MCP server.

    Returns (ok, tool_names, error_message).
    """
    session = requests.Session()
    try:
        init = _mcp_post(
            session,
            url,
            auth_header,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "atlassian-chat-agent",
                        "version": "1.0.0",
                    },
                },
            },
            session_id=None,
            timeout=timeout,
        )
        if init.status_code in (401, 403):
            return False, [], f"HTTP {init.status_code} (auth/scope): {init.text[:200]}"
        if init.status_code >= 400:
            return False, [], f"HTTP {init.status_code}: {init.text[:200]}"

        session_id = init.headers.get("Mcp-Session-Id") or init.headers.get(
            "mcp-session-id"
        )

        # Notify the server initialization is complete (best-effort).
        try:
            _mcp_post(
                session,
                url,
                auth_header,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                session_id=session_id,
                timeout=timeout,
            )
        except requests.RequestException:
            pass

        listing = _mcp_post(
            session,
            url,
            auth_header,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_id=session_id,
            timeout=timeout,
        )
        body = _parse_mcp_body(listing)
        if body and isinstance(body.get("result"), dict):
            tools = body["result"].get("tools")
            if tools is not None:
                names = [t.get("name", "?") for t in tools]
                if listing.status_code >= 400:
                    return True, names, (
                        f"(HTTP {listing.status_code} at tools/list; tool "
                        "execution will require a valid token/scopes)"
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


def preflight_mcp(servers: List[Dict[str, str]], auth_header: str) -> bool:
    """Run mcp_list_tools against each server, printing a report."""
    rule("MCP server connectivity preflight")
    all_ok = True
    for s in servers:
        name, url = s["name"], s["url"]
        good, tools, error = mcp_list_tools(url, auth_header)
        if good:
            ok(f"{name:9s} {url}")
            print(_c(f"    tools ({len(tools)}): " + ", ".join(tools), C.DIM))
            if error:
                print(_c(f"    note: {error}", C.YELLOW))
        else:
            all_ok = False
            err(f"{name:9s} {url}")
            print(_c(f"    {error}", C.DIM))
    return all_ok


# ---------------------------------------------------------------------------
# Streaming render for Interactions API events.
# ---------------------------------------------------------------------------
class StreamRenderer:
    def __init__(self) -> None:
        self._in_text = False

    def _break_text(self) -> None:
        if self._in_text:
            print()
            self._in_text = False

    def handle_event(self, event: Any) -> None:
        event_type = getattr(event, "event_type", None)
        if event_type != "step.delta":
            return
        delta = getattr(event, "delta", None)
        if delta is None:
            return
        dtype = getattr(delta, "type", None)

        if dtype == "text":
            text = getattr(delta, "text", "") or ""
            if text:
                print(text, end="", flush=True)
                self._in_text = True
        elif dtype == "thought_summary":
            thought = getattr(delta, "text", "") or getattr(delta, "summary", "")
            if thought:
                self._break_text()
                print(_c(f"  [thinking] {thought}", C.DIM))
        elif dtype == "mcp_server_tool_call":
            self._break_text()
            server = getattr(delta, "server_name", "?")
            name = getattr(delta, "name", "?")
            args = getattr(delta, "arguments", {})
            args_str = json.dumps(args, ensure_ascii=False) if args else "{}"
            if len(args_str) > 200:
                args_str = args_str[:200] + "..."
            print(_c(f"  \u2192 tool call [{server}.{name}] {args_str}", C.BLUE))
        elif dtype == "mcp_server_tool_result":
            self._break_text()
            print(_c("  \u2190 tool result received", C.BLUE))
        elif dtype == "code_execution_result":
            result = getattr(delta, "result", "") or ""
            if result:
                self._break_text()
                print(_c(f"  [code result] {result}", C.DIM))

    def finish(self) -> None:
        self._break_text()


def extract_final_text(interaction: Any) -> str:
    """Pull the final model text out of a completed interaction object."""
    steps = getattr(interaction, "steps", None) or []
    for step in reversed(steps):
        content = getattr(step, "content", None) or []
        texts = []
        for part in content:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)
        if texts:
            return "".join(texts)
    return ""


# ---------------------------------------------------------------------------
# Running interactions.
# ---------------------------------------------------------------------------
def run_interaction(
    client: Any,
    agent_resource: str,
    prompt: str,
    tools: List[Dict[str, Any]],
    previous_interaction_id: Optional[str],
    stream: bool,
) -> Tuple[str, Optional[str]]:
    """Run one turn against a registered agent. Returns (final_text, interaction_id).

    The MCP `tools` (with the Atlassian auth header) are supplied turn-scoped at
    interaction time, so the API token is never stored on the agent.
    """
    kwargs: Dict[str, Any] = {
        "agent": agent_resource,
        "input": prompt,
        "tools": tools,
        "store": True,
    }
    if previous_interaction_id:
        kwargs["previous_interaction_id"] = previous_interaction_id

    if stream:
        renderer = StreamRenderer()
        interaction_id = None
        response_stream = client.interactions.create(
            stream=True, background=True, timeout=900, **kwargs
        )
        for event in response_stream:
            renderer.handle_event(event)
            # Lifecycle events carry the id needed to chain a stateful multi-turn
            # conversation.
            inter = getattr(event, "interaction", None)
            iid = (
                getattr(inter, "id", None)
                or getattr(event, "interaction_id", None)
                or getattr(event, "id", None)
            )
            if iid:
                interaction_id = iid
        renderer.finish()
        return "", interaction_id

    interaction = client.interactions.create(**kwargs)
    final_text = extract_final_text(interaction)
    print(final_text)
    return final_text, getattr(interaction, "id", None)


# ---------------------------------------------------------------------------
# Client setup + Control Plane.
# ---------------------------------------------------------------------------
def init_genai_client(project: Optional[str] = None) -> Tuple[Any, str]:
    """Initialize the enterprise Gen AI client using ADC. Returns (client, project).

    NOTE: Use the unified Google Gen AI SDK (`google-genai >= 2.0.0`). Legacy SDKs
    (`google-cloud-aiplatform`, `google-generativeai`) do NOT support the
    Interactions API.
    """
    import google.auth
    from google import genai

    _, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    project_id = (
        project
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or adc_project
    )
    if not project_id:
        raise RuntimeError(
            "Could not resolve a GCP project. Pass --project <PROJECT_ID>, run "
            "`gcloud config set project <PROJECT_ID>`, or set GOOGLE_CLOUD_PROJECT."
        )
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"
    client = genai.Client(enterprise=True, project=project_id, location=LOCATION)
    return client, project_id


def get_control_plane_token() -> str:
    """Return an ADC access token (cloud-platform) for Agents Control Plane REST."""
    import google.auth
    from google.auth.transport.requests import Request

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(Request())
    return creds.token


def register_agent(
    project: str,
    token: str,
    agent_id: str,
    base_agent: str,
    description: str,
    system_instruction: Optional[str],
) -> str:
    """Register a custom agent via the Control Plane and wait until it is ready.

    Returns the full agent resource name. This project only supports agent-based
    interactions, so we register an agent before calling it. The MCP tools + auth
    header are supplied later, at interaction time (never stored on the agent).
    """
    base = f"https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{LOCATION}"
    resource = f"projects/{project}/locations/{LOCATION}/agents/{agent_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload: Dict[str, Any] = {
        "id": agent_id,
        "base_agent": base_agent,
        "description": description,
        # A base environment is required for agent interactions. The Rovo MCP
        # server is reached over the network, so allow outbound egress.
        "base_environment": {
            "type": "remote",
            "sources": [],
            "network": {"allowlist": [{"domain": "*"}]},
        },
    }
    if system_instruction:
        payload["system_instruction"] = system_instruction

    resp = requests.post(f"{base}/agents", headers=headers, json=payload, timeout=60)
    if resp.status_code not in (200, 409):
        raise RuntimeError(f"Failed to create agent: HTTP {resp.status_code} {resp.text}")
    if resp.status_code == 409:
        return resource

    operation_name = resp.json().get("name")
    if operation_name:
        # Poll the LRO until the agent container is ready.
        deadline = time.time() + 180
        while time.time() < deadline:
            poll = requests.get(
                f"https://aiplatform.googleapis.com/v1beta1/{operation_name}",
                headers=headers,
                timeout=60,
            )
            data = poll.json()
            if data.get("done"):
                if "error" in data:
                    raise RuntimeError(f"Agent registration failed: {data['error']}")
                break
            time.sleep(3)
    return resource


def delete_agent(project: str, token: str, agent_id: str) -> None:
    """Best-effort delete of the agent created for this run."""
    url = (
        f"https://aiplatform.googleapis.com/v1beta1/projects/{project}"
        f"/locations/{LOCATION}/agents/{agent_id}"
    )
    try:
        requests.delete(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=60
        )
    except requests.RequestException:
        pass


# ---------------------------------------------------------------------------
# Modes.
# ---------------------------------------------------------------------------
def run_interactive(
    client: Any,
    agent_resource: str,
    tools: List[Dict[str, Any]],
    stream: bool,
) -> None:
    rule("Interactive session (type 'exit' or Ctrl-D to quit)")
    previous_id: Optional[str] = None
    while True:
        try:
            prompt = input(_c("\nyou > ", C.BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit"):
            break
        print(_c("agent >", C.BOLD))
        try:
            _, iid = run_interaction(
                client, agent_resource, prompt, tools, previous_id, stream
            )
            if iid:
                previous_id = iid
        except Exception as e:  # noqa: BLE001
            err(f"Interaction failed: {e}")


def run_examples(
    client: Any,
    agent_resource: str,
    examples: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    stream: bool,
) -> int:
    failures = 0
    for i, example in enumerate(examples, start=1):
        title = example.get("title", f"example_{i}")
        prompt = example.get("prompt", "")
        rule(f"[{i}/{len(examples)}] {title}")
        print(_c("prompt: ", C.BOLD) + prompt)
        print(_c("agent >", C.BOLD))
        try:
            run_interaction(client, agent_resource, prompt, tools, None, stream)
        except Exception as e:  # noqa: BLE001
            failures += 1
            err(f"Interaction failed: {e}")
    return failures


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Standalone multi-turn runner for the Atlassian Chat Agent."
    )
    parser.add_argument(
        "prompt", nargs="?", help="Ad-hoc prompt to run (overrides agent.yaml examples)."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(SCRIPT_DIR, "agent.yaml"),
        help="Path to agent.yaml.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Preflight only: verify the Atlassian token + MCP connectivity, then exit.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List tools exposed by the Rovo MCP server for your token, then exit.",
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Run an interactive multi-turn chat."
    )
    parser.add_argument(
        "--servers",
        help="Comma-separated server names to use (from agent.yaml `mcp_servers`).",
    )
    parser.add_argument(
        "--mcp-url",
        help=f"Override the MCP server URL (default from agent.yaml / {DEFAULT_MCP_URL}).",
    )
    parser.add_argument(
        "--auth-mode",
        choices=["basic", "bearer"],
        help="Atlassian auth mode: 'basic' (personal token) or 'bearer' (service key). "
        "Overrides agent.yaml `auth.mode`.",
    )
    parser.add_argument("--email", help="Atlassian account email (Basic auth).")
    parser.add_argument("--api-token", help="Atlassian personal API token (Basic auth).")
    parser.add_argument("--api-key", help="Atlassian service-account API key (Bearer auth).")
    parser.add_argument(
        "--base-agent",
        help="Override the base_agent (runtime) from agent.yaml, e.g. "
        "antigravity-preview-05-2026.",
    )
    parser.add_argument(
        "--agent-id",
        help="Reuse a fixed agent id instead of a random one (implies you may "
        "want --keep-agent).",
    )
    parser.add_argument(
        "--keep-agent",
        action="store_true",
        help="Do not delete the registered agent after the run.",
    )
    parser.add_argument(
        "--project",
        help="GCP project for the Interactions API (overrides GOOGLE_CLOUD_PROJECT "
        "and the ADC-resolved project).",
    )
    parser.add_argument(
        "--no-stream", action="store_true", help="Disable response streaming."
    )
    args = parser.parse_args()

    # Load config.
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        err(f"Config not found: {args.config}")
        return 1

    base_agent = args.base_agent or config.get(
        "base_agent", "antigravity-preview-05-2026"
    )
    system_instruction = load_system_instruction()
    servers_filter = (
        [s.strip() for s in args.servers.split(",") if s.strip()]
        if args.servers
        else None
    )
    servers = resolve_servers(config, servers_filter, args.mcp_url)
    if not servers:
        err("No MCP servers selected. Check agent.yaml `mcp_servers` / --servers.")
        return 1

    rule("Atlassian Chat Agent — runner")
    info(f"Base agent: {base_agent}")
    info(f"Servers:    {', '.join(s['name'] + ' -> ' + s['url'] for s in servers)}")

    # Step 1: build the Atlassian auth header from an API token.
    rule("Building Atlassian authorization (API token)")
    try:
        auth_header = build_atlassian_auth_header(config, args)
        ok("Authorization header ready.")
    except Exception as e:  # noqa: BLE001
        err(str(e))
        return 1

    # Steps that only need the token + MCP server (no Interactions API call).
    if args.check or args.list_tools:
        good = preflight_mcp(servers, auth_header)
        if args.check:
            rule("Preflight summary")
            (ok if good else warn)(
                "Rovo MCP server reachable." if good else "Rovo MCP server failed."
            )
            info(
                "ADC/project check runs when you start an interaction "
                "(omit --check/--list-tools)."
            )
        return 0 if good else 2

    # Step 2: Interactions API client (ADC).
    rule("Initializing Interactions API client (ADC)")
    try:
        client, project_id = init_genai_client(project=args.project)
        ok(f"Gen AI client ready (project={project_id}, location={LOCATION}).")
    except Exception as e:  # noqa: BLE001
        err(f"Failed to init Gen AI client: {e}")
        return 1

    tools = build_mcp_tools(servers, auth_header)
    stream = not args.no_stream

    # Step 3: Register the agent (Control Plane). The MCP tools/auth header are
    # supplied per-turn at interaction time, so no secret is stored on the agent.
    rule("Registering agent (Control Plane)")
    agent_id = args.agent_id or f"atlassian-chat-{uuid.uuid4().hex[:12]}"
    keep_agent = args.keep_agent
    try:
        cp_token = get_control_plane_token()
        agent_resource = register_agent(
            project=project_id,
            token=cp_token,
            agent_id=agent_id,
            base_agent=base_agent,
            description=config.get("description", "Atlassian chat agent."),
            system_instruction=system_instruction,
        )
        ok(f"Agent ready: {agent_resource}")
    except Exception as e:  # noqa: BLE001
        err(f"Failed to register agent: {e}")
        return 1

    # Step 4: run interactions against the agent, then clean up.
    try:
        if args.interactive:
            run_interactive(client, agent_resource, tools, stream)
            return 0

        if args.prompt:
            examples = [{"title": "manual_run", "prompt": args.prompt}]
        else:
            examples = config.get("examples", []) or [
                {"title": "default", "prompt": "What can you help me with in Jira and Confluence?"}
            ]

        failures = run_examples(client, agent_resource, examples, tools, stream)
        rule("Done")
        if failures:
            err(f"{failures}/{len(examples)} interaction(s) failed.")
            return 2
        ok(f"All {len(examples)} interaction(s) completed.")
        return 0
    finally:
        if keep_agent:
            info(f"Leaving agent in place (--keep-agent): {agent_id}")
        else:
            delete_agent(project_id, cp_token, agent_id)
            info(f"Cleaned up agent: {agent_id}")


if __name__ == "__main__":
    sys.exit(main())
