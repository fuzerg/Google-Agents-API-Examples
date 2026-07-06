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
showcase/
├── README.md                   # This master guide
├── requirements.txt            # Local development dependencies
├── prober.py                   # Unified Vertex AI test runner & client
│
├── code_optimizer/             # Showcase 1: Code Optimizer
│   ├── agent.yaml
│   ├── AGENTS.md
│   └── README.md
│
├── financial_analyst/          # Showcase 2: Smart Financial Analyst
│   ├── agent.yaml
│   ├── AGENTS.md
│   ├── README.md
│   └── skills/                 # Custom GCS-mounted helper module
│
├── github_automation/          # Showcase 3: GitHub PR Creator
│   ├── agent.yaml
│   ├── AGENTS.md
│   ├── README.md
│   └── skills/                 # GitHub REST API helper class
│
├── mcp_support/                # Showcase 4: IT Support Bot (MCP)
│   ├── agent.yaml
│   ├── AGENTS.md
│   ├── README.md
│   └── mcp_server.py           # Local system monitor server
│
└── github_code_optimizer/      # Showcase 5: GitHub Code Optimizer
    ├── agent.yaml
    ├── AGENTS.md
    ├── README.md
    ├── slow_code.py            # Target Python code to optimize
    └── skills/                 # GitHub REST API helper class
```

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
Navigate to the `showcase` directory and set up the virtual environment:
```bash
cd showcase
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

All examples are executed via the unified `prober.py` script from the `showcase` root directory:
```bash
./venv/bin/python3 showcase/prober.py showcase/<example_name>
```

Refer to the individual README files in each folder for specific prerequisites (such as API tokens or hosting helper servers) before running:

1.  **Code Optimizer**: [code_optimizer/README.md](file:///Users/zhaofu/workspace/interactions_api/showcase/code_optimizer/README.md)
    *   *No special credentials required.*
    *   Command: `./venv/bin/python3 showcase/prober.py showcase/code_optimizer`
2.  **Smart Financial Analyst**: [financial_analyst/README.md](file:///Users/zhaofu/workspace/interactions_api/showcase/financial_analyst/README.md)
    *   *Requires GCS skill mounting.*
    *   Command: `./venv/bin/python3 showcase/prober.py showcase/financial_analyst`
3.  **GitHub PR Creator**: [github_automation/README.md](file:///Users/zhaofu/workspace/interactions_api/showcase/github_automation/README.md)
    *   *Requires `GITHUB_PAT` and repository details (or mock setup).*
    *   Command: `./venv/bin/python3 showcase/prober.py showcase/github_automation`
4.  **IT Support Bot (MCP)**: [mcp_support/README.md](file:///Users/zhaofu/workspace/interactions_api/showcase/mcp_support/README.md)
    *   *Requires starting the local MCP server and exposing a tunnel.*
    *   Command: `./venv/bin/python3 showcase/prober.py showcase/mcp_support`
5.  **GitHub Code Optimizer**: [github_code_optimizer/README.md](file:///Users/zhaofu/workspace/interactions_api/showcase/github_code_optimizer/README.md)
    *   *Requires `GITHUB_PAT` and repository details (or mock setup).*
    *   Command: `./venv/bin/python3 showcase/prober.py showcase/github_code_optimizer`

