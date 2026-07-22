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

Because the agent is self-contained, you can also keep it (`--keep-agent`) and
then chat with it interactively via the sibling `chat.py` (a template-agnostic
interactive client): `chat.py --agent <id>`.

Usage:
  python3 agent_templates/prober.py <template_dir> [prompt]
  python3 agent_templates/prober.py <template_dir> --check        # MCP preflight
  python3 agent_templates/prober.py <template_dir> --list-tools
  python3 agent_templates/prober.py <template_dir> --keep-agent   # keep + print id
"""

import argparse
import copy
import os
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

    # Auto-load the template's .env so credentials referenced by agent.yaml's
    # per-server `auth` blocks are available without manually sourcing it.
    ak.load_dotenv(os.path.join(template_dir, ".env"))

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


def _bucket_url(gcs_uri):
    """`gs://bucket/path/...` -> `gs://bucket` (the bucket root)."""
    rest = gcs_uri[len("gs://"):] if gcs_uri.startswith("gs://") else gcs_uri
    return "gs://" + rest.split("/", 1)[0]


def _ensure_bucket(gcs_uri):
    """Create the bucket that backs `gcs_uri` if it does not already exist."""
    bucket_url = _bucket_url(gcs_uri)
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


def _require_resolved_gs(uri, what):
    """Fail clearly if `uri` is not a fully-resolved gs:// path."""
    if not isinstance(uri, str) or not uri.startswith("gs://") or "${" in uri:
        sys.exit(
            f"{what} must be a resolved gs:// path, got: {uri!r}. If it references "
            f"an env var (e.g. ${{GCS_BUCKET}}), set that variable in your shell or "
            f"the template's .env."
        )


def maybe_upload_local_data(template_dir, env_config):
    """Mirror each source's `x-upload-from` local dir to its GCS `source`.

    Every `environment.sources` entry may declare `x-upload-from: <dir>` (a path
    relative to the template dir). prober mirrors that directory to the entry's
    `source` (creating the bucket if needed) using `rsync`, so the GCS copy is an
    exact mirror of the local files (no stale leftovers). `x-upload-from` is a
    prober-only field; `strip_prober_source_keys` removes it before registration.
    """
    for src in env_config.get("sources", []) or []:
        if src.get("type") != "gcs":
            continue
        upload_from = src.get("x-upload-from")
        if not upload_from:
            continue
        dest = src.get("source", "")
        _require_resolved_gs(dest, f"source for x-upload-from '{upload_from}'")
        local = os.path.join(template_dir, upload_from)
        if not os.path.isdir(local):
            sys.exit(f"x-upload-from points to a missing directory: {local}")
        _ensure_bucket(dest)
        print(f"Uploading '{local}' -> {dest} ...")
        subprocess.run(
            ["gcloud", "storage", "rsync", "-r",
             "--delete-unmatched-destination-objects", local, dest],
            check=True,
        )


def strip_prober_source_keys(env_config):
    """Drop prober-only keys from sources so the payload is API-clean."""
    for src in env_config.get("sources", []) or []:
        src.pop("x-upload-from", None)


def resolve_output(config):
    """Return (target, bucket) from `x-output-mount`, or (None, None).

    `x-output-mount` is an object:
        x-output-mount:
          target: /workspace/output          # sandbox mount point
          bucket: gs://.../output             # base; prober appends /{agent_id}
    """
    out = config.get("x-output-mount")
    if not out:
        return None, None
    if not isinstance(out, dict):
        sys.exit("x-output-mount must be a mapping with `target` and `bucket`.")
    target, bucket = out.get("target"), out.get("bucket")
    if not target or not bucket:
        sys.exit("x-output-mount requires both `target` and `bucket`.")
    _require_resolved_gs(bucket, "x-output-mount.bucket")
    return target, bucket


def download_output(output_source, template_dir, output_target):
    """Download the agent's output GCS prefix to a local directory.

    All sessions of the agent write to `output_source` (`{bucket}/{agent_id}`)
    with distinct filenames (AGENTS.md instructs the agent not to overwrite), so a
    single download collects every session's files.
    """
    target_name = os.path.basename(output_target.rstrip("/"))
    local_output_dir = os.path.join(template_dir, target_name)
    os.makedirs(local_output_dir, exist_ok=True)
    print(f"\nDownloading output files from {output_source}/* ...")
    time.sleep(3)
    res = subprocess.run(
        ["gcloud", "storage", "cp", "-r", f"{output_source}/*", local_output_dir],
        capture_output=True, text=True,
    )
    if res.returncode == 0:
        ak.ok(f"Output files saved to: {local_output_dir}")
    else:
        ak.warn(f"Failed to download output files: {res.stderr}")


def resolve_examples(config, prompt_override):
    if prompt_override:
        return [{"title": "manual_run", "prompt": prompt_override}]
    return config.get("examples", []) or [{"title": "default_run", "prompt": "Hello"}]


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

    # Auth + project.
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

    tools, servers = assemble_tools(config)
    system_instruction = ak.load_system_instruction(template_dir) or config.get("instructions")
    base_agent = config.get("base_agent", ak.DEFAULT_BASE_AGENT)
    description = config.get("description", "")
    env_config = config.get("environment", {}) or {}

    # Handle x-upload-from
    maybe_upload_local_data(template_dir, env_config)
    strip_prober_source_keys(env_config)

    output_target, output_bucket = resolve_output(config)
    examples = resolve_examples(config, args.prompt)

    try:
        client, project_id = ak.init_genai_client(project=project_id)
    except Exception as e:  # noqa: BLE001
        print(f"Failed to init Gen AI client: {e}")
        return 1

    agent_id = f"{config.get('id')}-{uuid.uuid4().hex[:8]}"
    output_source = None
    if output_bucket:
        output_source = f"{output_bucket.rstrip('/')}/{agent_id}"
        sources = copy.deepcopy(env_config.get("sources", []) or [])
        sources.append({"type": "gcs", "source": output_source, "target": output_target})
        env_config = {**env_config, "sources": sources}
    base_environment = ak.default_base_environment(env_config, allow_network=bool(servers))

    print(f"Registering agent '{agent_id}' via Control Plane...")
    try:
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

    # Data Plane: run every example against the one agent, then clean up.
    try:
        for i, example in enumerate(examples):
            ak.rule(f"[{i + 1}/{len(examples)}] {example.get('title', f'example_{i}')}")
            print(f"Prompt: {example.get('prompt', 'Hello')}\n")
            try:
                ak.stream_interaction(
                    client, agent_resource, example.get("prompt", "Hello"),
                    renderer=ak.SimpleRenderer(),
                )
                print(f"\nInteraction {i + 1} finished successfully.")
            except Exception as e:  # noqa: BLE001
                ak.err(f"An error occurred during interaction {i + 1}: {e}")

        if output_source:
            download_output(output_source, template_dir, output_target)
    finally:
        if args.keep_agent:
            ak.rule("Agent kept")
            ak.ok(f"Agent id: {agent_id}")
            if output_source:
                print(f"Output prefix:  {output_source}")
            print(f"Chat with it:  chat.py --agent {agent_id} --project {project_id}")
        else:
            print(f"\nCleaning up: deleting agent '{agent_id}'...")
            ak.delete_agent(project_id, ak.access_token(credentials), agent_id)
            ak.ok("Agent deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
