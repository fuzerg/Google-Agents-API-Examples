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
streaming multi-turn REPL against an **already-registered** agent, chaining turns
via `previous_interaction_id`:

  --agent <id|resource>   Chat with a self-contained agent (e.g. one provisioned
                          earlier with `prober.py <template> --keep-agent`). Each
                          turn is just {agent, input}, no tools injected.

Provisioning lives in `prober.py`: it handles the full template lifecycle (GCS
skills, `x-*` extensions, MCP servers + auth) and can leave a self-contained
agent behind with `--keep-agent`. `chat.py` stays focused on interactive chat and
never registers or deletes agents.

All shared logic (auth, client, streaming) lives in `agentkit.py`.

Example:
  # Chat with an existing agent (e.g. one kept via `prober.py <template> --keep-agent`):
  python3 agent_templates/chat.py --agent <agent-id> --project YOUR_PROJECT
"""

import argparse
import os
import sys

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
                stream=stream, renderer=ak.RichRenderer(),
            )
            if iid:
                previous_id = iid
        except Exception as e:  # noqa: BLE001
            ak.err(f"Interaction failed: {e}")


def main() -> int:
    p = argparse.ArgumentParser(description="Interactive chat client for an agent.")
    p.add_argument("--agent", required=True,
                   help="Existing agent id or full resource name to chat with "
                        "(e.g. one kept via `prober.py <template> --keep-agent`).")
    p.add_argument("--project", help="GCP project (else GOOGLE_CLOUD_PROJECT / ADC).")
    p.add_argument("--no-stream", action="store_true", help="Disable response streaming.")
    args = p.parse_args()

    stream = not args.no_stream

    ak.rule("Chat client")
    try:
        client, project_id = ak.init_genai_client(project=args.project)
        ak.ok(f"Gen AI client ready (project={project_id}, location={ak.LOCATION}).")
    except Exception as e:  # noqa: BLE001
        ak.err(f"Failed to init Gen AI client: {e}")
        return 1

    agent_resource = ak.agent_resource_name(args.agent, project_id)
    ak.info(f"Chatting with: {agent_resource}")
    run_repl(client, agent_resource, stream)
    return 0


if __name__ == "__main__":
    sys.exit(main())
