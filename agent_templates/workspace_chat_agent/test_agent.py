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
"""Standalone test runner for the Google Workspace Chat Agent.

This script exercises the agent end-to-end WITHOUT prober.py:

  1. Resolves your Application Default Credentials (ADC) + project for the
     Interactions API (the Data Plane call to the Gemini Enterprise Agent
     Platform).
  2. Mints an end-user OAuth 2.0 access token with Workspace scopes (browser
     consent on first run, cached + auto-refreshed afterwards).
  3. Optionally connects directly to each Google-hosted Workspace MCP server and
     lists its tools, as a fast connectivity/auth preflight (`--check`).
  4. Runs stateful, streaming Interactions where the model is given the Workspace
     MCP servers as `mcp_server` tools (Authorization: Bearer <user token>),
     letting it read and act on your Gmail / Drive / Calendar / People / Chat.

Usage:
  # One-time / preflight: verify ADC, OAuth token, and MCP connectivity.
  python3 test_agent.py --check

  # List the tools each enabled MCP server exposes.
  python3 test_agent.py --list-tools

  # Run all example prompts from agent.yaml.
  python3 test_agent.py

  # Run a single ad-hoc prompt.
  python3 test_agent.py "Summarize my unread email from today."

  # Interactive multi-turn chat (stateful).
  python3 test_agent.py --interactive

  # Restrict to specific servers.
  python3 test_agent.py --servers gmail,calendar "What's on my plate today?"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

import workspace_auth

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCATION = "global"
MCP_PROTOCOL_VERSION = "2025-06-18"


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
    config: Dict[str, Any], servers_filter: Optional[List[str]]
) -> List[Dict[str, str]]:
    """Return the list of {name,url} MCP servers to use."""
    all_servers = config.get("mcp_servers", []) or []
    selected = []
    for s in all_servers:
        name = s.get("name")
        url = s.get("url")
        if not name or not url:
            continue
        if servers_filter is not None:
            if name in servers_filter:
                selected.append({"name": name, "url": url})
        elif s.get("enabled", True):
            selected.append({"name": name, "url": url})
    return selected


def build_mcp_tools(
    servers: List[Dict[str, str]], access_token: str
) -> List[Dict[str, Any]]:
    """Turn the server list into Interactions API `mcp_server` tool specs."""
    tools = []
    for s in servers:
        tools.append(
            {
                "type": "mcp_server",
                "name": s["name"],
                "url": s["url"],
                "headers": {"Authorization": f"Bearer {access_token}"},
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
    token: str,
    payload: dict,
    session_id: Optional[str],
    timeout: int,
) -> requests.Response:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return session.post(url, headers=headers, json=payload, timeout=timeout)


def mcp_list_tools(
    url: str, token: str, timeout: int = 30
) -> Tuple[bool, List[str], str]:
    """Directly initialize + list tools on a remote MCP server.

    Returns (ok, tool_names, error_message).
    """
    session = requests.Session()
    try:
        init = _mcp_post(
            session,
            url,
            token,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "workspace-chat-agent-test",
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
                token,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                session_id=session_id,
                timeout=timeout,
            )
        except requests.RequestException:
            pass

        listing = _mcp_post(
            session,
            url,
            token,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_id=session_id,
            timeout=timeout,
        )
        # Some servers return the tool list in the body even alongside a non-200
        # status (e.g. Gmail answers tools/list with a 401 but still includes the
        # catalog). Surface tools whenever the body carries them.
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


def preflight_mcp(servers: List[Dict[str, str]], token: str) -> bool:
    """Run mcp_list_tools against each server, printing a report."""
    rule("MCP server connectivity preflight")
    all_ok = True
    for s in servers:
        name, url = s["name"], s["url"]
        good, tools, error = mcp_list_tools(url, token)
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

    The MCP `tools` (with the per-user bearer header) are supplied turn-scoped at
    interaction time, so the short-lived token is never stored on the agent.
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
            # Lifecycle events (interaction.created/completed/status_update)
            # carry the id needed to chain a stateful multi-turn conversation.
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
# Client setup.
# ---------------------------------------------------------------------------
def init_genai_client(project: Optional[str] = None) -> Tuple[Any, str]:
    """Initialize the enterprise Gen AI client using ADC. Returns (client, project).

    An explicit `project` (e.g. from --project) takes precedence over the
    GOOGLE_CLOUD_PROJECT env var and the ADC-resolved project.
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
    """Register a custom agent via the Control Plane and wait for it to be ready.

    Returns the full agent resource name. This project only supports agent-based
    interactions (model-based interactions are disabled), so we must register an
    agent before calling it. MCP tools are supplied later, at interaction time.
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
        # A base environment is required for agent interactions. The MCP servers
        # are reached over the network, so allow outbound egress.
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
    """Best-effort delete of the agent created for this test run."""
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


def obtain_token(config: Dict[str, Any], args: argparse.Namespace) -> Tuple[str, dict]:
    """Mint/refresh the Workspace OAuth token. Returns (access_token, tokeninfo)."""
    scopes = config.get("oauth_scopes", []) or []
    if not scopes:
        raise RuntimeError("No oauth_scopes defined in agent.yaml.")

    # Shortcut: reuse the ADC user credential as the MCP bearer. This avoids
    # creating an OAuth client / consent screen, but requires that ADC was
    # logged in WITH the Workspace scopes, e.g.:
    #   gcloud auth application-default login --scopes=<oauth_scopes from agent.yaml>
    if args.use_adc_token:
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default(scopes=scopes)
        creds.refresh(Request())
        tokeninfo = workspace_auth.introspect_token(creds.token)
        granted = set(tokeninfo.get("scope", "").split())
        workspace_scopes = [s for s in scopes if s.startswith("https://www.googleapis.com/auth/")
                            and "userinfo" not in s]
        missing = [s for s in workspace_scopes if s not in granted]
        if missing:
            warn(
                "Your ADC token is missing Workspace scopes: "
                + ", ".join(s.rsplit("/", 1)[-1] for s in missing)
            )
            print(
                _c(
                    "    Re-login ADC with the scopes from agent.yaml:\n"
                    "      gcloud auth application-default login --scopes="
                    + ",".join(scopes),
                    C.YELLOW,
                )
            )
        return creds.token, tokeninfo

    client_secret = (
        args.client_secret
        or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE")
        or os.path.join(SCRIPT_DIR, "client_secret.json")
    )
    token_file = args.token or os.path.join(SCRIPT_DIR, "token.json")
    login_hint = args.login_hint or os.environ.get("USER_GOOGLE_EMAIL")

    creds = workspace_auth.get_workspace_credentials(
        scopes=scopes,
        client_secret_file=client_secret,
        token_file=token_file,
        login_hint=login_hint,
        force_reauth=args.reauth,
        open_browser=not args.no_browser,
    )
    tokeninfo = workspace_auth.introspect_token(creds.token)
    return creds.token, tokeninfo


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
        description="Standalone tester for the Google Workspace Chat Agent."
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
        help="Preflight only: verify ADC, OAuth token, and MCP connectivity, then exit.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List tools exposed by each enabled MCP server, then exit.",
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Run an interactive multi-turn chat."
    )
    parser.add_argument(
        "--servers",
        help="Comma-separated server names to use (e.g. gmail,calendar). "
        "Overrides the `enabled` flags in agent.yaml.",
    )
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
        "--use-adc-token",
        action="store_true",
        help="Reuse the ADC user credential as the MCP bearer token (no OAuth "
        "client needed). Requires `gcloud auth application-default login "
        "--scopes=<oauth_scopes>` first.",
    )
    parser.add_argument("--client-secret", help="Path to OAuth client_secret.json.")
    parser.add_argument("--token", help="Path to the cached token JSON file.")
    parser.add_argument("--login-hint", help="Email to pre-select during consent.")
    parser.add_argument(
        "--reauth", action="store_true", help="Force a fresh OAuth consent flow."
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open a browser for the OAuth consent flow.",
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
    servers = resolve_servers(config, servers_filter)
    if not servers:
        err("No MCP servers selected. Check agent.yaml `mcp_servers` / --servers.")
        return 1

    rule("Google Workspace Chat Agent — test runner")
    info(f"Base agent: {base_agent}")
    info(f"Servers:    {', '.join(s['name'] for s in servers)}")

    # Step 1: OAuth token for the Workspace MCP servers.
    rule("Authorizing Google Workspace access (OAuth 2.0)")
    try:
        access_token, tokeninfo = obtain_token(config, args)
    except FileNotFoundError as e:
        err(str(e))
        return 1
    except Exception as e:  # noqa: BLE001
        err(f"Failed to obtain Workspace OAuth token: {e}")
        return 1

    email = tokeninfo.get("email", "<unknown>")
    granted = tokeninfo.get("scope", "")
    ok(f"Authorized as: {email}")
    if granted:
        print(_c("    granted scopes:", C.DIM))
        for scope in granted.split():
            print(_c(f"      - {scope}", C.DIM))

    # Steps that only need the token + MCP servers (no Interactions API call).
    if args.check or args.list_tools:
        good = preflight_mcp(servers, access_token)
        if args.check:
            rule("Preflight summary")
            (ok if good else warn)(
                "All MCP servers reachable." if good else "Some MCP servers failed."
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

    tools = build_mcp_tools(servers, access_token)
    stream = not args.no_stream

    # Step 3: Register the agent (Control Plane). This project supports only
    # agent-based interactions, so we register an agent, run against it, then
    # delete it. The MCP tools/bearer are supplied per-turn at interaction time.
    rule("Registering agent (Control Plane)")
    agent_id = args.agent_id or f"workspace-chat-test-{uuid.uuid4().hex[:12]}"
    keep_agent = args.keep_agent
    try:
        cp_token = get_control_plane_token()
        agent_resource = register_agent(
            project=project_id,
            token=cp_token,
            agent_id=agent_id,
            base_agent=base_agent,
            description=config.get("description", "Google Workspace chat agent."),
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
                {"title": "default", "prompt": "What can you help me with in my Workspace?"}
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
