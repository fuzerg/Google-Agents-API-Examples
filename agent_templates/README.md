# Gemini Enterprise Agent Platform — Developer Showcase (Templates)

This showcase contains a collection of templates for building and deploying Gemini Managed Agents on the Gemini Enterprise Agent Platform (Vertex AI). These examples demonstrate the power of the platform, including server-side code execution, filesystem operations, GCS skills, web search, and Model Context Protocol (MCP) integrations.

Following the platform templates pattern, all examples here are **fully configuration-based**, sharing a single unified test runner, with individual settings and behavior described in declarative YAML and markdown files.

---

## Repository Structure

Each example is housed in its own folder and contains:
1.  **`agent.yaml`**: Configures the agent ID, base agent model, tools, network access rules, and contains sample inputs/examples.
2.  **`AGENTS.md`**: Provides the system instructions that define the agent's persona and core workflows.
3.  **`README.md`**: Contains detailed setups, flow diagrams, and specific prerequisites for the example.
4.  **`skills/`** (Optional): Mounted custom Python helpers or instructions loaded into the agent's runtime environment.
5.  **`.env`** (Optional, git-ignored): Local credentials (e.g. API tokens) that `prober.py` auto-loads before parsing `agent.yaml`. Templates that need secrets typically ship a **`.env.example`** to copy from. See [Environment Variables & `.env`](#environment-variables--env).

```
agent_templates/
├── README.md                   # This master guide
├── requirements.txt            # Local development dependencies
├── agentkit.py                 # Shared toolkit (auth, client, control plane, streaming, MCP)
├── prober.py                   # Unified provisioner + single-turn example runner
├── chat.py                     # Template-agnostic interactive multi-turn chat client
│
├── financial_analyst/          # Showcase 1: Smart Financial Analyst
├── github_code_optimizer/      # Showcase 2: GitHub Code Optimizer (Remote MCP)
├── atlassian_chat_agent/       # Showcase 3: Atlassian Chat Agent (Remote MCP)
└── app_developer/              # Showcase 4: General-Purpose Coding Agent (Remote MCP)
```

### Two runners, one shared toolkit

Both runners import `agentkit.py`, which holds the shared machinery (ADC auth,
Gen AI client init, agent register/delete on the Control Plane, streaming
interactions + renderers, and generic MCP helpers). Both are **template-agnostic**
and live next to `agentkit.py`; each entrypoint stays thin:

*   **`prober.py <template_dir>`** — the **unified provisioner + single-turn
    example runner** for every template. It registers a *self-contained* agent
    (baking in the template's tools, including remote MCP servers with their auth
    headers) and runs the `examples` from `agent.yaml`. Flags: `--check` /
    `--list-tools` (MCP preflight), `--keep-agent` (keep + print the agent id).
*   **`chat.py --agent <id>`** — a template-agnostic **interactive multi-turn
    chat client**. Point it at an existing self-contained agent (e.g. one kept
    with `prober.py <template> --keep-agent`) and chat. It never provisions or
    deletes agents — because prober registers agents self-contained, this thin
    client can drive them with just `{agent, input}`.

---

## Unified `agent.yaml` Configuration

Each showcase template relies on a declarative `agent.yaml` file that defines the agent's properties, tools, runtime environment, and test examples. The `prober.py` script automatically parses this file and uses it to provision the agent in the cloud.

### Environment Variables & `.env`

`agent.yaml` is declarative but can reference environment variables, so no secrets
or machine-specific values are hardcoded in the file. When `prober.py` loads a
template, env vars are resolved in two steps:

1.  **`.env` auto-load.** If the template directory has a `.env`, `prober.py` loads
    its `KEY=VALUE` lines into the process environment *first* (via
    `agentkit.load_dotenv`). The parser is dependency-free: it skips blank lines and
    `#` comments, tolerates a leading `export `, and strips surrounding quotes.
    **Shell-exported variables win** — a value already set in your shell is never
    overridden by `.env`. Templates that need credentials typically ship a
    `.env.example`; copy it to `.env` and fill in your values (`.env` is git-ignored).
2.  **`${VAR}` expansion.** The raw YAML text is expanded *before* it is parsed, so
    `${VAR}` / `$VAR` anywhere in the file is substituted with the corresponding
    environment value — e.g. `source: gs://${GCS_BUCKET}/financial_analyst/skills`.
    An **unset** variable is left **literally in place** (e.g. `${MISSING}`) rather
    than raising, so double-check spelling for optional fields.

> **Note:** values inside an `mcp_servers[].auth.headers` block use a *stricter*
> interpolation than the whole-file pass above: it additionally supports the
> `${base64:...}` transform and **raises a clear error on an unset variable** (so a
> missing token fails fast instead of shipping a broken header). See
> [Header value interpolation](#remote-mcp-servers-mcp_servers) below.

### Core Fields
*   **`id`**: A unique string identifier for the agent (e.g., `financial-analyst-showcase`). The prober adds a randomized UUID suffix to prevent naming collisions.
*   **`base_agent`**: The foundational agent model used for generation (e.g., `antigravity-preview-05-2026`).
*   **`description`**: A human-readable description of what the agent does.
*   **`tools`**: A list of server-managed tools granted to the agent.
    *   Examples: `- type: google_search` or `- type: code_execution`.

### Environment (`environment`)
Configures the sandbox runtime in which the agent executes its tools (like `code_execution`).
*   **`type`**: Usually set to `"remote"` to denote execution on cloud servers.
*   **`sources`**: A list of external data sources to mount into the agent's execution environment.
    *   `type`: e.g., `"gcs"` for Google Cloud Storage.
    *   `source`: The remote path that is mounted.
    *   `target`: The absolute path where the source is mounted inside the agent.
    *   `x-upload-from` *(optional, prober-only)*: A local directory (relative to the template) that `prober.py` **mirrors** to `source` before registering the agent (via `gcloud storage rsync`, creating the bucket if needed). Omit it when `source` already exists in GCS (user-managed).
*   **`network.allowlist`**: Defines network access rules for the sandbox. Example: `- domain: "*"` allows unrestricted outbound internet access.

```yaml
environment:
  type: "remote"
  sources:
    - type: "gcs"
      source: "gs://${GCS_BUCKET}/financial_analyst/skills"  # mount + upload dest
      target: "/.agents/skills"                               # -> /.agents/skills/<name>/...
      x-upload-from: "skills"                                 # local folder prober mirrors to `source`
```

### Remote MCP Servers (`mcp_servers`)
Connects the agent to one or more remote [MCP](https://modelcontextprotocol.io) servers. Each entry is turned into an `mcp_server` tool and baked into the agent, so the model can call the server's tools.
*   **`name`**: A short identifier for the server (e.g., `atlassian`).
*   **`url`**: The MCP endpoint the platform routes tool calls to.
*   **`enabled`**: Optional (default `true`); set `false` to skip the server.
*   **`auth`**: Optional. Per-server authentication, expressed as a raw **`headers`** map that the platform forwards to `url` (and nothing else).

```yaml
mcp_servers:
  - name: my-server
    url: https://mcp.example.com/v1/mcp
    auth:
      headers:
        Authorization: "Bearer ${MY_API_KEY}"
        X-Api-Version: "2024-01"
```

**Header value interpolation.** Values are resolved at runtime from your
environment (nothing secret is stored in the file). Two forms are supported:

| Syntax | Expands to | Use for |
| --- | --- | --- |
| `${VAR}` / `$VAR` | the env var's value | Bearer tokens, API keys, custom headers |
| `${base64:VAR1:VAR2:...}` | base64 of the colon-joined env values | HTTP **Basic** auth |

HTTP Basic requires `base64(user:pass)` (RFC 7617), not a raw `user:pass`, so use
the `${base64:...}` transform, e.g.:

```yaml
auth:
  headers:
    Authorization: "Basic ${base64:MY_EMAIL:MY_TOKEN}"   # -> Basic <base64(email:token)>
```

A referenced env var that is unset raises a clear error. This `auth` block is a
convention of this repo's runners (parsed by `agentkit`); it simply populates the
standard `mcp_server` tool `headers` field.

### Custom Prober Extensions (`x-` prefixed)
These fields are not part of the standard Agent API payload but are used by `prober.py` to orchestrate local/remote testing workflows. (`x-upload-from` on a source, covered above, is another.)
*   **`x-output-mount`**: Declares a writable output location for generated files (PDFs, charts, etc.). It is an object with two keys:
    *   `target`: the absolute path inside the sandbox the agent writes to (e.g. `/workspace/output`).
    *   `bucket`: the base GCS path you own (e.g. `gs://${GCS_BUCKET}/financial_analyst/output`).

    `prober.py` bakes a per-agent, run-unique output source — `{bucket}/{agent_id}` — into the agent's **`base_environment`** at registration and mounts it at `target`. Because it lives in the agent (not a per-interaction override), **every** session of that agent writes there — including later interactive sessions via `chat.py`. All those sessions share the one `{bucket}/{agent_id}` prefix, so instruct the agent (in `AGENTS.md`) to use **distinct output filenames** and avoid overwriting. After the examples finish, `prober.py` downloads `{bucket}/{agent_id}/*` into a local `output/` directory next to the template.

    ```yaml
    x-output-mount:
      target: "/workspace/output"
      bucket: "gs://${GCS_BUCKET}/financial_analyst/output"
    ```

### Test Cases (`examples`)
*   **`examples`**: A list of test iterations the prober will run sequentially.
    *   `title`: A unique name for the test run (used to name local output directories).
    *   `prompt`: The initial user input sent to the agent.

---

## Setup & Prerequisites

Before running the examples, ensure you have:
1.  **Python 3.10+** installed.
2.  A valid Google Cloud Platform (GCP) Project with Vertex AI API enabled.
3.  Logged in to your GCP account via Application Default Credentials (ADC):
    ```bash
    gcloud auth application-default login
    ```

### Configure the Virtual Environment
Navigate to the `agent_templates` directory and set up the virtual environment:
```bash
cd agent_templates
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Set the target project ID in your terminal session:
```bash
export GCP_PROJECT="your-gcp-project-id-here"
```

---

## Running the Examples

All examples are executed via the unified `prober.py` script from the `agent_templates` root directory:
```bash
./venv/bin/python3 agent_templates/prober.py agent_templates/<example_name>
```

Refer to the individual README files in each folder for specific prerequisites (such as API tokens or hosting helper servers) before running:

1.  **Smart Financial Analyst**: [financial_analyst/README.md](file:///Users/zhaofu/workspace/interactions_api/agent_templates/financial_analyst/README.md)
    *   *Requires GCS skill mounting.*
    *   Command: `./venv/bin/python3 agent_templates/prober.py agent_templates/financial_analyst`
2.  **GitHub Code Optimizer (Remote MCP)**: [github_code_optimizer/README.md](file:///Users/zhaofu/workspace/interactions_api/agent_templates/github_code_optimizer/README.md)
    *   *Benchmarks in the sandbox and performs all GitHub operations via GitHub's hosted remote MCP server. Requires a `GITHUB_TOKEN` (PAT); nothing to host.*
    *   Preflight the MCP server: `./venv/bin/python3 agent_templates/prober.py agent_templates/github_code_optimizer --list-tools`
    *   Command: `./venv/bin/python3 agent_templates/prober.py agent_templates/github_code_optimizer`
3.  **Atlassian Chat Agent (Remote MCP)**: [atlassian_chat_agent/README.md](file:///Users/zhaofu/workspace/interactions_api/agent_templates/atlassian_chat_agent/README.md)
    *   *Uses Atlassian's hosted Rovo MCP server (Jira + Confluence). Requires an Atlassian API token; nothing to host.*
    *   Run its examples: `./venv/bin/python3 agent_templates/prober.py agent_templates/atlassian_chat_agent`
    *   Chat interactively: keep an agent, then attach — `./venv/bin/python3 agent_templates/prober.py agent_templates/atlassian_chat_agent --keep-agent` then `./venv/bin/python3 agent_templates/chat.py --agent <agent-id>`
4.  **General-Purpose Coding Agent (Remote MCP)**: [app_developer/README.md](file:///Users/zhaofu/workspace/interactions_api/agent_templates/app_developer/README.md)
    *   *Turns a request into tested code on GitHub: builds a new app and creates+pushes a new repo (greenfield), or implements a feature in an existing repo and opens a PR (feature). Verifies tests in the sandbox before publishing, via GitHub's hosted remote MCP server. Requires a `GITHUB_TOKEN` (PAT — classic `repo` scope covers both modes); nothing to host.*
    *   Preflight the MCP server: `./venv/bin/python3 agent_templates/prober.py agent_templates/app_developer --list-tools`
    *   Command: `./venv/bin/python3 agent_templates/prober.py agent_templates/app_developer`

