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
"""Interactive multi-turn chat client for a Gemini Enterprise agent.

`chat.py` is a thin, generic conversational front-end. It runs a stateful,
streaming multi-turn REPL against an agent, chaining turns via
`previous_interaction_id`. Two ways to point it at an agent:

  --agent <id|resource>   Chat with an already-registered, self-contained agent
                          (e.g. one provisioned earlier with
                          `prober.py <template> --keep-agent`). This is the
                          generic path any unified chat client would use: each
                          turn is just {agent, input}, no tools injected.

  --from-template <dir>   Convenience: register a self-contained agent from a
                          template's agent.yaml (baking in its MCP server + auth
                          header via the Control Plane), chat with it, and delete
                          it on exit (unless --keep-agent).

All shared logic (auth, client, control plane, streaming, MCP helpers) lives in
`agentkit.py`.

This client is template-agnostic: it has no task-specific logic and works with
any agent template (it reads `mcp_servers` + per-server `auth` from the template's
agent.yaml).

Examples:
  # Provision from a template dir, chat, then clean up:
  python3 agent_templates/chat.py --from-template agent_templates/<template> --project YOUR_PROJECT

  # Chat with an existing agent (e.g. one kept via `prober.py <template> --keep-agent`):
  python3 agent_templates/chat.py --agent <agent-id> --project YOUR_PROJECT
"""

import argparse
import os
import sys
import uuid

# agentkit.py lives in the same directory as this script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentkit as ak  # noqa: E402


def run_repl(client, agent_resource: str, stream: bool) -> None:
    """Interactive multi-turn loop; chains turns via previous_interaction_id."""
    ak.rule("Interactive session (type 'exit' or Ctrl-D to quit)")
    previous_id = None
    while True:
        try:
            prompt = input(ak.c("\nyou > ", ak.C.BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit"):
            break
        print(ak.c("agent >", ak.C.BOLD))
        try:
            _, iid = ak.stream_interaction(
                client, agent_resource, prompt,
                previous_interaction_id=previous_id,
                stream=stream,
                renderer=ak.Renderer(color=True, show_thoughts=True, show_tools=True),
            )
            if iid:
                previous_id = iid
        except Exception as e:  # noqa: BLE001
            ak.err(f"Interaction failed: {e}")


def provision_from_template(args, project_id, token):
    """Register a self-contained agent from a template dir. Returns (resource, id)."""
    template_dir = os.path.abspath(args.from_template)
    # Auto-load the template's .env so per-server `auth` credentials are present.
    ak.load_dotenv(os.path.join(template_dir, ".env"))
    config = ak.load_config(os.path.join(template_dir, "agent.yaml"))
    system_instruction = ak.load_system_instruction(template_dir)

    servers = ak.resolve_servers(config, url_override=args.mcp_url)
    if not servers:
        raise RuntimeError("Template declares no `mcp_servers` to attach.")
    # Each server carries its own per-server `auth` block (resolved from env vars
    # it names); build_mcp_tools makes a distinct Authorization header per server.
    tools = ak.build_mcp_tools(servers)

    agent_id = args.agent_id or f"{config.get('id', 'chat-agent')}-{uuid.uuid4().hex[:8]}"
    base_agent = args.base_agent or config.get("base_agent", ak.DEFAULT_BASE_AGENT)

    ak.rule("Provisioning self-contained agent from template (Control Plane)")
    ak.info(f"Template: {template_dir}")
    ak.info(f"Servers:  {', '.join(s['name'] + ' -> ' + s['url'] for s in servers)}")
    resource = ak.register_agent(
        project=project_id, token=token, agent_id=agent_id,
        base_agent=base_agent, description=config.get("description", "Chat agent."),
        system_instruction=system_instruction, tools=tools,
        base_environment=ak.default_base_environment(
            config.get("environment", {}) or {}, allow_network=True
        ),
    )
    ak.ok(f"Agent ready: {resource}")
    return resource, agent_id


def main() -> int:
    p = argparse.ArgumentParser(description="Interactive chat client for an agent.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--agent", help="Existing agent id or full resource name to chat with.")
    src.add_argument("--from-template", metavar="DIR",
                     help="Register a self-contained agent from this template dir, "
                          "chat, then delete on exit (unless --keep-agent).")
    p.add_argument("--project", help="GCP project (else GOOGLE_CLOUD_PROJECT / ADC).")
    p.add_argument("--no-stream", action="store_true", help="Disable response streaming.")
    p.add_argument("--keep-agent", action="store_true",
                   help="With --from-template: keep the agent after exit.")
    # --from-template options. MCP auth is declared per server in agent.yaml
    # (`mcp_servers[].auth`) and resolved from the env vars it names.
    p.add_argument("--agent-id", help="Fixed agent id for --from-template.")
    p.add_argument("--base-agent", help="Override base_agent for --from-template.")
    p.add_argument("--mcp-url", help="Override a single MCP server URL for --from-template.")
    args = p.parse_args()

    stream = not args.no_stream

    ak.rule("Chat client")
    try:
        client, project_id = ak.init_genai_client(project=args.project)
        ak.ok(f"Gen AI client ready (project={project_id}, location={ak.LOCATION}).")
    except Exception as e:  # noqa: BLE001
        ak.err(f"Failed to init Gen AI client: {e}")
        return 1

    # Mode A: attach to an existing agent.
    if args.agent:
        agent_resource = ak.agent_resource_name(args.agent, project_id)
        ak.info(f"Chatting with: {agent_resource}")
        run_repl(client, agent_resource, stream)
        return 0

    # Mode B: provision from a template, chat, then clean up.
    try:
        credentials, _ = ak.resolve_adc()
        token = ak.access_token(credentials)
    except Exception as e:  # noqa: BLE001
        ak.err(f"Auth failed: {e}")
        return 1

    try:
        agent_resource, agent_id = provision_from_template(args, project_id, token)
    except Exception as e:  # noqa: BLE001
        ak.err(f"Failed to provision agent: {e}")
        return 1

    try:
        run_repl(client, agent_resource, stream)
    finally:
        if args.keep_agent:
            ak.rule("Agent kept")
            ak.ok(f"Reuse it later:  chat.py --agent {agent_id} --project {project_id}")
        else:
            ak.delete_agent(project_id, ak.access_token(credentials), agent_id)
            ak.info(f"Cleaned up agent: {agent_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
