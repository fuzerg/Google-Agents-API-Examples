# Automated GitHub Code Optimizer (Remote MCP Route)

This developer showcase demonstrates how to build an agent that retrieves slow
code from a GitHub repository, benchmarks it in a secure Cloud Sandbox, designs
and benchmarks an optimized version, and opens a Pull Request with a
comprehensive description of the performance improvements.

It combines the **code-execution benchmarking** technique with **GitHub's
official remote MCP server** for all repository operations. There is **nothing to
host** and **no custom helper code**: the platform securely routes the model's
GitHub tool calls (read file, create branch, commit, open PR) to
`https://api.githubcopilot.com/mcp/`, authenticated with your Personal Access
Token.

> This is the MCP counterpart to the classic "GCS-mounted skill" pattern. The
> repository operations that used to live in a bundled `github_helper.py` are now
> first-class MCP tool calls; the sandbox is used only for benchmarking.

---

## How It Works

```
 ┌──────────────────────┐
 │     Local Client     │
 │ (Unified prober.py)  │
 └──────────┬───────────┘
            │ (1) Registers a self-contained agent: code_execution tool +
            │     github remote MCP server (with Bearer PAT header baked in)
            │ (2) Starts a stateful, streaming interaction
            ▼
 ┌────────────────────────────────────────────────────────┐
 │                   Gemini Agent Platform                 │
 │                                                        │
 │  ┌──────────────────────────────────────────────────┐  │
 │  │              Agent Container (Cloud)             │  │
 │  │ (3) Calls the github MCP tool to read the file   │  │
 │  │ (4) Benchmarks original code in the sandbox      │  │
 │  │ (5) Writes optimized code & benchmarks speedup   │  │
 │  │                                                  │  │
 │  │   ┌──────────────────────────────────────────┐   │  │
 │  │   │          Code Execution Sandbox          │   │  │
 │  │   │  timeit baseline vs. optimized, verify   │   │  │
 │  │   └──────────────────────────────────────────┘   │  │
 │  └───────────────────────┬──────────────────────────┘  │
 │           (6) Tool calls: create_branch, create/update  │
 │               file, create_pull_request                 │
 └───────────────────────────┼────────────────────────────┘
                             │  platform routes tool calls with the
                             │  Authorization: Bearer <PAT> header
                             ▼
                  ┌────────────────────────────┐
                  │  GitHub Remote MCP Server  │
                  │ api.githubcopilot.com/mcp/ │
                  └─────────────┬──────────────┘
                                ▼
                        ┌─────────────────┐
                        │   GitHub (PR)   │
                        └─────────────────┘
```

1.  **Provisioning**: `prober.py` parses `agent.yaml` and registers a
    *self-contained* agent whose tools are the `code_execution` sandbox plus the
    `github` remote MCP server. The `GITHUB_TOKEN` from this template's `.env` is
    interpolated into the MCP server's `Authorization: Bearer …` header and baked
    into the agent — no credential is stored in the YAML.
2.  **Retrieval**: The agent calls the GitHub MCP "get file contents" tool to
    fetch the target file from `main`.
3.  **Benchmarking**: The agent benchmarks the original in the sandbox, designs
    an optimized implementation, and benchmarks the two comparatively to prove
    the speedup and confirm identical results.
4.  **PR creation**: The agent calls the GitHub MCP tools to create a unique
    branch, commit the optimized file, and open a **new** Pull Request back to
    `main` with the benchmark results and an explanation of the speedup.
5.  **Result**: The agent ends its message with the resulting Pull Request URL
    as a plain, clickable link.

---

## Setup & Requirements

### 1. Prerequisites
Complete the global showcase prerequisites (see the parent
[`agent_templates/README.md`](../README.md)):
*   Python 3.10+ and requirements installed in your virtual environment.
*   GCP Application Default Credentials (ADC) logged in.
*   The Vertex AI API enabled.

### 2. Obtain a GitHub Personal Access Token (PAT)
The remote GitHub MCP server accepts any valid GitHub access token; this template
passes a PAT as a Bearer token.
1.  Go to **GitHub Settings** → **Developer Settings** → **Personal Access
    Tokens** → **Fine-grained tokens** (or Tokens Classic).
2.  Grant **Repository permissions**:
    *   **Contents**: `Read and write` (read/write files, create branches).
    *   **Pull Requests**: `Read and write` (open the PR).
3.  Copy the token value.

### 3. Provide the token
Set the token in your shell **or** in this template's `.env` file (git-ignored);
`prober.py` loads the template `.env` automatically:
```bash
export GITHUB_TOKEN="github_pat_your_token_value_here"
```
> Never commit a real token. The `.env` file in this directory is ignored by git.

### 4. (Optional) Scope the tool surface
`agent.yaml` sets `X-MCP-Toolsets: "repos,pull_requests"` so the agent only sees
the repository and pull-request tools it needs. Edit or remove that header to
expose more (or the full default) toolset, or add `X-MCP-Readonly: "true"` to
forbid writes. See the
[remote server docs](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md).

---

## Running the Example

1.  (Optional) **Preflight the MCP connection** — verify the token/URL and list
    the tools the server exposes before provisioning an agent:
    ```bash
    ./venv/bin/python3 agent_templates/prober.py agent_templates/github_code_optimizer --check
    ./venv/bin/python3 agent_templates/prober.py agent_templates/github_code_optimizer --list-tools
    ```
2.  **Run the examples:**
    ```bash
    ./venv/bin/python3 agent_templates/prober.py agent_templates/github_code_optimizer
    ```
3.  The agent streams its progress and ends with the created Pull Request URL as
    a plain, clickable link:
    ```
    https://github.com/your_github_username/your_repository_name/pull/99
    ```
