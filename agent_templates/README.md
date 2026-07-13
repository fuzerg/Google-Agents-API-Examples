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

```
agent_templates/
├── README.md                   # This master guide
├── requirements.txt            # Local development dependencies
├── prober.py                   # Unified Vertex AI test runner & client
│
├── financial_analyst/          # Showcase 1: Smart Financial Analyst
│   ├── agent.yaml
│   ├── AGENTS.md
│   ├── README.md
│   └── skills/                 # Custom GCS-mounted helper module
│
├── github_code_optimizer/      # Showcase 2: GitHub Code Optimizer
│   ├── agent.yaml
│   ├── AGENTS.md
│   ├── README.md
│   ├── slow_code.py            # Target Python code to optimize
│   └── skills/                 # GitHub REST API helper class
│
├── mcp_support/                # Showcase 3: IT Support Bot (MCP)
│   ├── agent.yaml
│   ├── AGENTS.md
│   ├── README.md
│   └── mcp_server.py           # Local system monitor server
│
└── atlassian_chat_agent/       # Showcase 4: Atlassian Chat Agent (Remote MCP)
    ├── agent.yaml
    ├── AGENTS.md
    ├── README.md
    ├── chat.py                 # Multi-turn runner (replaces prober.py)
    └── .env.example            # Atlassian API-token credentials template
```

---

## Unified `agent.yaml` Configuration

Each showcase template relies on a declarative `agent.yaml` file that defines the agent's properties, tools, runtime environment, and test examples. The `prober.py` script automatically parses this file and uses it to provision the agent in the cloud.

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
    *   `source`: The remote path (e.g., `gs://${GCS_BUCKET}/financial_analyst`).
    *   `target`: The absolute path where the source will be mounted inside the agent's environment (e.g., `/.agents/skills/financial_analyst`).
*   **`network.allowlist`**: Defines network access rules for the sandbox. Example: `- domain: "*"` allows unrestricted outbound internet access.

### Custom Prober Extensions (`x-` prefixed)
These fields are not part of the standard Agent API payload but are used by `prober.py` to orchestrate advanced local/remote testing workflows.
*   **`x-output-mount`**: Specifies an absolute path inside the agent's sandbox (e.g., `/workspace/output`) where generated files (like PDFs or charts) will be saved. `prober.py` dynamically creates a unique GCS bucket folder for each example, maps it to this target during execution, and then automatically syncs all generated files back to your local workspace (`output_{example_title}`) when the interaction completes.
*   **`x-env-secrets`**: A list of local environment variable names (e.g., `- GITHUB_TOKEN`). `prober.py` will read these variables from your host machine and securely inject them as `.env` files into any local `skills/` directories before uploading them to the cloud.
*   **`x-extract-messages`**: A list of parsing rules to extract specific text blocks from the agent's streaming output based on `start` and `end` string markers.

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
2.  **GitHub Code Optimizer**: [github_code_optimizer/README.md](file:///Users/zhaofu/workspace/interactions_api/agent_templates/github_code_optimizer/README.md)
    *   *Requires `GITHUB_TOKEN` environment variable.*
    *   Command: `./venv/bin/python3 agent_templates/prober.py agent_templates/github_code_optimizer`
3.  **IT Support Bot (MCP)**: [mcp_support/README.md](file:///Users/zhaofu/workspace/interactions_api/agent_templates/mcp_support/README.md)
    *   *Requires starting the local MCP server and exposing a tunnel.*
    *   Command: `./venv/bin/python3 agent_templates/prober.py agent_templates/mcp_support`
4.  **Atlassian Chat Agent (Remote MCP)**: [atlassian_chat_agent/README.md](file:///Users/zhaofu/workspace/interactions_api/agent_templates/atlassian_chat_agent/README.md)
    *   *Multi-turn agent using Atlassian's hosted Rovo MCP server (Jira + Confluence). Requires an Atlassian API token; nothing to host.*
    *   *Uses its own `chat.py` runner instead of `prober.py`.*
    *   Command: `cd agent_templates/atlassian_chat_agent && ./venv/bin/python3 chat.py --interactive`

