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
"""Unified provisioner + single-turn example runner for agent templates.

`prober.py` parses a template's `agent.yaml`, provisions a **self-contained**
custom agent on Vertex AI (Control Plane) — baking in its tools, including any
remote MCP servers with their auth headers — and runs the template's declared
`examples` as stateful, streaming, single-turn interactions (Data Plane).

It works for every template in this repo:
  * skills-based templates: local `skills/` are uploaded to GCS and mounted, and
    the `x-env-secrets`, `x-output-mount`, and `x-extract-messages` extensions
    are honored.
  * MCP templates: each `mcp_servers` entry (with its own per-server `auth`)
    becomes an `mcp_server` tool with an Authorization header, baked into the
    agent so it is self-contained.

Because the agent is self-contained, you can also keep it (`--keep-agent`) and
then chat with it interactively via `chat.py --agent <id>`.

Usage:
  python3 agent_templates/prober.py <template_dir> [prompt]
  python3 agent_templates/prober.py <template_dir> --check        # MCP preflight
  python3 agent_templates/prober.py <template_dir> --list-tools
  python3 agent_templates/prober.py <template_dir> --keep-agent   # keep + print id

Shared logic (auth, client, control plane, streaming) lives in `agentkit.py`.
"""

import argparse
import copy
import os
import re
import subprocess
import sys
import time
import uuid

# Make the shared toolkit importable regardless of the current working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentkit as ak  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Provision an agent template and run its examples."
    )
    p.add_argument("template_dir", help="Path to the template directory.")
    p.add_argument("prompt", nargs="?", help="Ad-hoc prompt (overrides examples).")
    p.add_argument("--check", action="store_true",
                   help="MCP connectivity/auth preflight, then exit (MCP templates).")
    p.add_argument("--list-tools", action="store_true",
                   help="List tools the template's MCP server exposes, then exit.")
    p.add_argument("--keep-agent", action="store_true",
                   help="Do not delete the agent after running; print its id so "
                        "you can chat with it via `chat.py --agent <id>`.")
    p.add_argument("--project", help="GCP project (else GOOGLE_CLOUD_PROJECT / ADC).")
    return p.parse_args()


def load_template(template_dir):
    template_dir = template_dir.rstrip("/")
    if not os.path.isdir(template_dir):
        print(f"Error: Directory '{template_dir}' not found.")
        sys.exit(1)
    agent_yaml = os.path.join(template_dir, "agent.yaml")
    if not os.path.exists(agent_yaml):
        print(f"Error: agent.yaml not found in {template_dir}")
        sys.exit(1)

    # MCP self-hosted templates normalize MCP_SERVER_URL -> /sse before expansion.
    mcp_url = os.environ.get("MCP_SERVER_URL")
    if mcp_url:
        if not mcp_url.rstrip("/").endswith("/sse"):
            mcp_url = mcp_url.rstrip("/") + "/sse"
        os.environ["MCP_SERVER_URL"] = mcp_url

    config = ak.load_config(agent_yaml, expandvars=True)
    return template_dir, config


def assemble_tools(config):
    """Agent tools = explicit `tools` + MCP tools derived from `mcp_servers`.

    Each MCP server carries its own per-server `auth` block, so `build_mcp_tools`
    builds a distinct Authorization header per server.
    """
    tools = list(config.get("tools", []) or [])
    servers = ak.resolve_servers(config)
    if servers:
        tools.extend(ak.build_mcp_tools(servers))
    return tools, servers


def upload_skills(template_dir, config, project_id, gcs_bucket):
    """Inject x-env-secrets, then upload local skills/ to GCS (skills templates)."""
    local_skills_dir = os.path.join(template_dir, "skills")
    if not os.path.exists(local_skills_dir):
        return

    secrets_config = config.get("x-env-secrets", {})
    created_env_files = []
    for skill_name, secrets in secrets_config.items():
        skill_dir = os.path.join(local_skills_dir, skill_name)
        if os.path.exists(skill_dir):
            env_path = os.path.join(skill_dir, ".env")
            with open(env_path, "w") as f:
                for secret in secrets:
                    f.write(f'{secret}="{os.environ.get(secret, "")}"\n')
            created_env_files.append(env_path)

    try:
        bucket_url = f"gs://{gcs_bucket}"
        exists = subprocess.run(
            ["gcloud", "storage", "buckets", "describe", bucket_url],
            capture_output=True,
        ).returncode == 0
        if not exists:
            print(f"Creating GCS bucket {bucket_url}...")
            subprocess.run(
                ["gcloud", "storage", "buckets", "create", bucket_url, "--location=us"],
                check=True,
            )
        for skill_name in os.listdir(local_skills_dir):
            skill_path = os.path.join(local_skills_dir, skill_name)
            if os.path.isdir(skill_path):
                print(f"Uploading skill files from '{skill_path}' to {bucket_url}/...")
                subprocess.run(
                    ["gcloud", "storage", "cp", "-r", skill_path, f"{bucket_url}/"],
                    check=True,
                )
    finally:
        for env_file in created_env_files:
            if os.path.exists(env_file):
                os.remove(env_file)


def run_examples(client, agent_resource, template_dir, config, agent_id,
                 gcs_bucket, env_config, prompt_override):
    """Run each example as a single-turn streaming interaction (+ x-* handling)."""
    if prompt_override:
        examples = [{"title": "manual_run", "prompt": prompt_override}]
    else:
        examples = config.get("examples", []) or [{"title": "default_run", "prompt": "Hello"}]

    output_mount = config.get("x-output-mount")
    extract_msgs = config.get("x-extract-messages", [])

    for i, example in enumerate(examples):
        prompt = example.get("prompt", "Hello")
        title = example.get("title", f"example_{i}")
        safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title).lower()

        # Per-interaction environment for output-mount templates.
        interaction_environment = None
        example_gcs_output = None
        if output_mount:
            example_gcs_output = f"gs://{gcs_bucket}/output_{agent_id}_{safe_title}"
            sources = copy.deepcopy(env_config.get("sources", []))
            sources.append({"type": "gcs", "source": example_gcs_output, "target": output_mount})
            interaction_environment = ak.default_base_environment(
                {**env_config, "sources": sources}
            )

        ak.rule(f"[{i + 1}/{len(examples)}] {title}")
        print(f"Prompt: {prompt}\n")
        try:
            final_text, _ = ak.stream_interaction(
                client, agent_resource, prompt,
                environment=interaction_environment,
                renderer=ak.SimpleRenderer(),
            )
            print(f"\nInteraction {i + 1} finished successfully.")

            if output_mount and example_gcs_output:
                target_name = os.path.basename(output_mount.rstrip("/"))
                local_output_dir = os.path.join(template_dir, f"{target_name}_{safe_title}")
                os.makedirs(local_output_dir, exist_ok=True)
                print(f"\nDownloading output files from {example_gcs_output}/* ...")
                time.sleep(3)
                res = subprocess.run(
                    ["gcloud", "storage", "cp", "-r", f"{example_gcs_output}/*", local_output_dir],
                    capture_output=True, text=True,
                )
                if res.returncode == 0:
                    ak.ok(f"Output files saved to: {local_output_dir}")
                else:
                    ak.warn(f"Failed to download output files: {res.stderr}")

            for ext in extract_msgs:
                start, end = ext.get("start"), ext.get("end")
                template = ext.get("message", "Extracted: {}")
                if start in final_text and end in final_text:
                    s = final_text.find(start) + len(start)
                    e = final_text.find(end, s)
                    if e > s:
                        print(f"\n\u2728 {template.format(final_text[s:e].strip())}")
        except Exception as e:  # noqa: BLE001
            ak.err(f"An error occurred during interaction {i + 1}: {e}")


def main() -> int:
    args = parse_args()
    template_dir, config = load_template(args.template_dir)

    # --check / --list-tools: MCP preflight only (no ADC / Control Plane needed).
    if args.check or args.list_tools:
        servers = ak.resolve_servers(config)
        if not servers:
            ak.err("This template declares no `mcp_servers`; nothing to preflight.")
            return 1
        good = ak.preflight_mcp(servers)
        return 0 if good else 2

    # Auth + project + client.
    try:
        credentials, adc_project = ak.resolve_adc()
        token = ak.access_token(credentials)
    except Exception as e:  # noqa: BLE001
        print(f"Authentication failed: {e}\nRun: gcloud auth application-default login")
        return 1
    project_id = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT") or adc_project
    if not project_id:
        print("GCP Project ID could not be resolved. Run: gcloud config set project <ID>")
        return 1
    print(f"Using GCP Project: {project_id}")

    gcs_bucket = os.environ.get("GCS_BUCKET_NAME", f"{project_id}-agent-skills")
    os.environ["GCS_BUCKET"] = gcs_bucket
    # Re-expand config now that GCS_BUCKET is set (sources reference it).
    _, config = load_template(args.template_dir)
    tools, servers = assemble_tools(config)

    system_instruction = config.get("instructions")
    system_instruction = ak.load_system_instruction(template_dir) or system_instruction

    agent_id = f"{config.get('id')}-{uuid.uuid4().hex[:8]}"
    base_agent = config.get("base_agent", ak.DEFAULT_BASE_AGENT)
    description = config.get("description", "")
    env_config = config.get("environment", {}) or {}

    # Upload skills to GCS if the template has a skills/ dir.
    upload_skills(template_dir, config, project_id, gcs_bucket)

    # Control Plane: register the self-contained agent (tools baked in).
    base_environment = ak.default_base_environment(env_config, allow_network=bool(servers))
    print(f"Registering agent '{agent_id}' via Control Plane...")
    try:
        client, project_id = ak.init_genai_client(project=project_id)
        agent_resource = ak.register_agent(
            project=project_id, token=token, agent_id=agent_id,
            base_agent=base_agent, description=description,
            system_instruction=system_instruction, tools=tools,
            base_environment=base_environment,
        )
        ak.ok(f"Agent registered: {agent_resource}")
    except Exception as e:  # noqa: BLE001
        print(f"Failed to register agent: {e}")
        return 1

    # Data Plane: run examples, then clean up (unless --keep-agent).
    try:
        run_examples(client, agent_resource, template_dir, config, agent_id,
                     gcs_bucket, env_config, args.prompt)
    finally:
        if args.keep_agent:
            ak.rule("Agent kept")
            ak.ok(f"Agent id: {agent_id}")
            print(f"Chat with it:  chat.py --agent {agent_id} --project {project_id}")
        else:
            print(f"\nCleaning up: deleting agent '{agent_id}'...")
            ak.delete_agent(project_id, ak.access_token(credentials), agent_id)
            ak.ok("Agent deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
