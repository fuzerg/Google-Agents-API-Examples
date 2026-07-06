# Automated GitHub Code Optimizer (Interactions API Cloud Sandbox Route)

This developer showcase example demonstrates how to build an agent that retrieves slow code from a GitHub repository, benchmarks it in a secure Cloud Sandbox, designs and benchmarks an optimized version, and opens a Pull Request with a comprehensive description of the performance improvements.

It combines the **code execution benchmarking** technique with the **GitHub API wrapper skill** to perform end-to-end performance optimization directly in the cloud.

---

## How It Works

```
 ┌──────────────────────┐
 │     Local Client     │
 │ (Unified prober.py)  │
 └──────────┬───────────┘
            │
            │ (1) Creates custom agent with GCS-mounted skill
            │ (2) Starts stateful, streaming interaction passing credentials
            ▼
 ┌────────────────────────────────────────────────────────┐
 │                   Gemini Agent Platform                 │
 │                                                        │
 │  ┌──────────────────────────────────────────────────┐  │
 │  │              Agent Container (Cloud)             │  │
 │  │                                                  │  │
 ┌────────────────────────────────────────────────────────┐
 │                   Gemini Agent Platform                 │
 │                                                        │
 │  ┌──────────────────────────────────────────────────┐  │
 │  │              Agent Container (Cloud)             │  │
 │  │                                                  │  │
 │  │ (3) Reads SKILL.md from /.agents/skills...       │  │
 │  │ (4) Retrieves fibonacci.py using GitHub REST API │  │
 │  │ (5) Runs benchmark on fibonacci.py in sandbox    │  │
 │  │ (6) Writes optimized code & runs speedup benchmark│  │
 │  │                                                  │  │
 │  │   ┌──────────────────────────────────────────┐   │  │
 │  │   │          Code Execution Sandbox          │   │  │
 │  │   │                                          │   │  │
 │  │   │ (7) Imports sys.path('/.agents/skills..')│   │  │
 │  │   │ (8) Calls github_helper.py functions     │   │  │
 │  │   └────────────────────┬─────────────────────┘   │  │
 │  └────────────────────────┼─────────────────────────┘  │
 └───────────────────────────┼────────────────────────────┘
                             │
                             │ (9) Commits optimized code & opens PR
                             ▼
                    ┌─────────────────┐
                    │   GitHub API    │
                    │   (GitHub PR)   │
                    └─────────────────┘
```

1.  **Provisioning & GCS Upload**: The prober script uploads the custom Python wrapper library (`github_helper.py`) and instructions (`SKILL.md`) to your GCS bucket. It also securely pipes your `GITHUB_TOKEN` into the bucket.
2.  **Custom Agent Deployment**: The Control Plane registers a stateful agent configuration in the cloud, specifying the GCS bucket source to mount to `/.agents/skills/github_automation`, and enables the `code_execution` sandbox tool.
3.  **Autonomous Sandbox Execution**: The agent receives the prompt.
4.  **Retrieval and Benchmarking**: The agent fetches the recursive `fibonacci` function from `fibonacci.py` via the GitHub REST API, runs a benchmark using `timeit` in the sandbox, designs an optimized O(N) implementation, and benchmarks the two versions comparatively.
4.  **GitHub PR Creation**: The agent creates a git branch, commits the optimized file, and opens a Pull Request back to `main` with a comprehensive description of the benchmark results and speedup explanations.
5.  **PR URL Extraction**: The generated Pull Request link is parsed and outputted by the prober script.

---

## Setup & Requirements

### 1. Prerequisites
Ensure you have completed the global showcase prerequisites:
*   Python 3.10+ and requirements installed in your virtual environment.
*   GCP Application Default Credentials (ADC) logged in.
*   The Vertex AI API enabled.

### 2. Obtain a GitHub Personal Access Token (PAT)
The agent needs a GitHub Personal Access Token (PAT) to perform repository actions.
1.  Go to **GitHub Settings** -> **Developer Settings** -> **Personal Access Tokens** -> **Fine-grained tokens** (or Tokens Classic).
2.  Generate a new token with **Repository permissions**:
    *   **Contents**: `Read and write` (to read/write files and create branches).
    *   **Pull Requests**: `Read and write` (to open the PR).
3.  Copy the token value.

### 3. Set the Environment Variables
Set your GitHub token in your terminal so the agent can authenticate when opening the pull request on `fuzerg/Slow-Code-Example`:
```bash
export GITHUB_TOKEN="github_pat_your_token_value_here"
```

---

## Running the Example

1.  Navigate to the showcase directory:
    ```bash
    cd showcase
    ```
2.  Run the prober:
    ```bash
    ./venv/bin/python3 showcase/prober.py showcase/github_code_optimizer
    ```

3.  The agent will start streaming its progress. Once finished, you will see a success message with the URL of the created Pull Request:
    ```
    ✨ Automated Pull Request created successfully: https://github.com/your_github_username/your_repository_name/pull/99
    ```
