# General-Purpose Coding Agent (Remote MCP Route)

This developer showcase demonstrates a coding agent that turns a natural-language
software request into **working, tested code on GitHub**. It operates in two
modes and picks the right one from your prompt:

- **Greenfield** — build a brand-new application from scratch, **create a new
  GitHub repository**, and push the project as its initial commit.
- **Feature** — implement a change/feature in an **existing repository** and open
  a Pull Request.

In both modes it writes a test suite and **verifies it in a secure Cloud
Sandbox** before publishing — it never publishes code it hasn't run.

It combines the **code-execution sandbox** (for writing and running the tests)
with **GitHub's official remote MCP server** (for every repository operation:
create repo, read files, commit/push, open PR). There is **nothing to host** and
**no custom helper code**: the platform securely routes the model's GitHub tool
calls to `https://api.githubcopilot.com/mcp/`, authenticated with your Personal
Access Token.

> Sibling templates: `github_code_optimizer/` (optimize an existing file → PR)
> and this one (build new apps / add features, greenfield or into an existing
> repo).

### Building UI / frontend apps

The agent **can build apps with a user interface** (React/Vue/Svelte, plain
HTML/CSS/JS, server-rendered, static sites, ...). Developing a UI doesn't require
rendering it: the agent writes the markup, styles, components, and logic as code
and verifies them **headlessly** — the project builds (`npm run build`),
type-checks/lints, and component/unit tests pass (e.g. Vitest/Jest + Testing
Library render to a virtual DOM, no real browser). The generated README includes
**preview instructions** so you can run and view the UI locally; live visual
review is the one step left to a human. The agent will not refuse a frontend task
just because the sandbox is headless.

A bundled **`playwright_visual_testing`** skill (in `skills/`, GCS-mounted into the
sandbox at `/.agents/skills/playwright_visual_testing`) gives the agent an optional,
tested recipe for **headless** browser visual/layout verification — installing the
browser dependencies, writing a visual spec, and safely handling PNG screenshot
binaries. It is a bonus the agent may use for UI work, never a requirement.

---

## How It Works

```
 ┌──────────────────────┐
 │     Local Client     │
 │ (Unified prober.py)  │
 └──────────┬───────────┘
            │ (1) Registers a self-contained agent: code_execution tool +
            │     github remote MCP server (with Bearer PAT header baked in)
            │ (2) Starts a stateful, streaming interaction (the request)
            ▼
 ┌────────────────────────────────────────────────────────┐
 │                   Gemini Agent Platform                 │
 │  ┌──────────────────────────────────────────────────┐  │
 │  │              Agent Container (Cloud)             │  │
 │  │ (3) Decide mode: greenfield vs. feature          │  │
 │  │ (4) Sandbox: write implementation + tests        │  │
 │  │ (5) Sandbox: run tests, iterate until green      │  │
 │  │                                                  │  │
 │  │   ┌──────────────────────────────────────────┐   │  │
 │  │   │          Code Execution Sandbox          │   │  │
 │  │   │  pip install, pytest/unittest, iterate   │   │  │
 │  │   └──────────────────────────────────────────┘   │  │
 │  └───────────────────────┬──────────────────────────┘  │
 │   (6) github MCP tool calls:                            │
 │       greenfield -> create_repository + push_files      │
 │       feature    -> create_branch + push_files + PR     │
 └───────────────────────────┼────────────────────────────┘
                             │  platform routes tool calls with the
                             │  Authorization: Bearer <PAT> header
                             ▼
                  ┌────────────────────────────┐
                  │  GitHub Remote MCP Server  │
                  │ api.githubcopilot.com/mcp/ │
                  └─────────────┬──────────────┘
                                ▼
                 ┌───────────────────────────────┐
                 │  GitHub (new repo, or a PR)   │
                 └───────────────────────────────┘
```

1.  **Provisioning**: `prober.py` registers a *self-contained* agent whose tools
    are the `code_execution` sandbox plus the `github` remote MCP server. The
    `GITHUB_TOKEN` from this template's `.env` is interpolated into the MCP
    server's `Authorization: Bearer …` header and baked into the agent — no
    credential is stored in the YAML.
2.  **Decide mode**: The agent chooses greenfield vs. feature from the prompt.
3.  **Build & verify**: In the sandbox, it writes the implementation and tests,
    installs dependencies, and runs the tests, iterating until they all pass.
4.  **Publish**:
    *   *Greenfield* — creates a new (public, initialized) repository and pushes
        the full project to the default branch.
    *   *Feature* — creates a unique branch, commits the change, and opens a new
        Pull Request.
5.  **Result**: The agent ends its message with the resulting URL as a plain,
    clickable link — a new repository URL (greenfield) or a Pull Request URL
    (feature).

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
passes a PAT as a Bearer token. The permissions it needs depend on the mode:

| Mode | Required token permissions |
| --- | --- |
| **Feature** (existing repo → PR) | On the target repo: **Contents** `Read and write`, **Pull Requests** `Read and write`. |
| **Greenfield** (create a new repo) | Permission to **create repositories** — e.g. a **classic** token with the `repo` scope (or a fine-grained token permitted to create repos for the account/org). |

> The simplest choice that covers both modes is a classic token with the `repo`
> scope.

### 3. Provide credentials
Copy `.env.example` to `.env` (git-ignored) and fill in the values, or export them
in your shell — `prober.py` picks up either. Two are needed:
*   **`GITHUB_TOKEN`** — the PAT above, baked into the GitHub MCP server's auth header.
*   **`GCS_BUCKET`** — a bucket you own; the whole local `skills/` folder (the
    `playwright_visual_testing` skill) is uploaded there and mounted into the sandbox.
```bash
cp agent_templates/app_developer/.env.example agent_templates/app_developer/.env
# then edit .env, or export directly:
export GITHUB_TOKEN="github_pat_your_token_value_here"
export GCS_BUCKET="your-gcs-bucket-name"
```
> Never commit a real token.

### 4. Targets & tool scoping
*   **Greenfield** examples create a new repo under the token's account — no
    target repo needed.
*   **Feature** examples target `fuzerg/Google-Agents-API-Examples`; edit the
    `Repository Owner`/`Repository Name` in the prompt to point at a repo your PAT
    can write to.
*   `agent.yaml` scopes the MCP tool surface via `X-MCP-Toolsets`
    (`repos,pull_requests`, which includes `create_repository`/`push_files`).
    Remove the header for the full default toolset, or add `X-MCP-Readonly:
    "true"` to forbid writes. See the
    [remote server docs](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md).

---

## Running the Example

1.  (Optional) **Preflight the MCP connection** — verify the token/URL and list
    the tools the server exposes before provisioning an agent:
    ```bash
    ./venv/bin/python3 agent_templates/prober.py agent_templates/app_developer --check
    ./venv/bin/python3 agent_templates/prober.py agent_templates/app_developer --list-tools
    ```
2.  **Run the bundled examples** (three greenfield, one feature):
    ```bash
    ./venv/bin/python3 agent_templates/prober.py agent_templates/app_developer
    ```
3.  **Provide your own request** instead of the bundled examples:
    ```bash
    # Greenfield -> new repo
    ./venv/bin/python3 agent_templates/prober.py agent_templates/app_developer \
      "Build a new Python 'markdown-to-html' CLI with tests; create a new public repo named markdown-to-html under my account and push it."

    # Feature -> PR into an existing repo
    ./venv/bin/python3 agent_templates/prober.py agent_templates/app_developer \
      "Add a retry decorator with exponential backoff and tests. Repository Owner: fuzerg, Repository Name: Google-Agents-API-Examples"
    ```
4.  The agent streams its progress and ends with the resulting URL as a plain,
    clickable link — either a new repository:
    ```
    https://github.com/your_username/quote-of-the-day
    ```
    or a Pull Request:
    ```
    https://github.com/owner/repo/pull/99
    ```
