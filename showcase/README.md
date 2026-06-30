# Gemini Enterprise Agent Platform - Developer Showcase

This showcase contains runnable Python examples demonstrating how to build advanced, stateful agentic workflows by combining the **Control Plane (Managed Agents API)** and the **Data Plane (Interactions API)** of the Gemini Enterprise Agent Platform.

These examples highlight the power of the platform:
1.  **Control Plane (REST)**: Programmatically provisioning, configuring, and deleting custom, stateful agent containers.
2.  **Data Plane (Unified SDK)**: Executing stateful, background-running interactions with support for real-time streaming, structured Pydantic outputs, server-side sandboxed tool execution, and remote MCP tool integration.

---

## Architecture: Control Plane vs. Data Plane

Understanding the division of labor between the Control Plane and the Data Plane is key to building on the platform:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           GCP Control Plane                             │
│  (Managed Agents API - REST)                                           │
│  - Provision Custom Agents (with system instructions, built-in tools)  │
│  - List, Update, and Delete Agent Containers                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Provisions Container)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            GCP Data Plane                               │
│  (Interactions API - google-genai SDK)                                  │
│  - Execute multi-turn, stateful conversations                           │
│  - Securely run server-side tools (e.g., Code Execution Sandbox)         │
│  - Invoke remote/local tools (e.g., Google Search, external MCP servers)│
│  - Stream responses and return structured JSON (Pydantic)               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

Before running the examples, ensure you have:
1.  **Python 3.10+** installed.
2.  A **Google Cloud Project** with the Vertex AI API enabled.
3.  **Application Default Credentials (ADC)** configured on your local machine.

### 1. Enable the Vertex AI API
Ensure the `aiplatform.googleapis.com` service is enabled in your Google Cloud project:
```bash
gcloud services enable aiplatform.googleapis.com
```

### 2. Authenticate via ADC
Authenticate your local terminal so the scripts can retrieve your project credentials:
```bash
gcloud auth application-default login
```
Ensure your active project is set (e.g., `agents-api-eval-143444`):
```bash
gcloud config set project YOUR_PROJECT_ID
```

---

## Setup

1.  Navigate to the `showcase` directory:
    ```bash
    cd showcase
    ```
2.  Create and activate a virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```

> [!NOTE]
> **Corporate Registry Workaround**:
> If you are on a corporate network/machine (like a Google corporate Mac) where the default `pip` registry is an internal staging index that lacks public packages, you can install the dependencies directly from the public PyPI by running:
> ```bash
> pip install --index-url https://pypi.org/simple -r requirements.txt
> ```

---

## The Examples

This showcase contains three examples. Each example has its own dedicated directory and detailed README:

1.  **[The Smart Financial Analyst](file:///Users/zhaofu/workspace/interactions_api/showcase/financial_analyst/README.md)**: Demonstrates combining server-side tools (Google Search) and custom GCS-mounted skills to perform stock analysis and generate a PDF report.
2.  **[The Code Optimizer](file:///Users/zhaofu/workspace/interactions_api/showcase/code_optimizer/README.md)**: Showcases real-time event-driven streaming of both model thoughts and server-side python sandbox execution.
3.  **[The Secure Hybrid MCP Support Bot](file:///Users/zhaofu/workspace/interactions_api/showcase/mcp_support/README.md)**: Demonstrates connecting a cloud agent to a local MCP server running on your machine via a secure tunnel.

---

## Developer Best Practices Highlighted

*   **Unified SDK**: Always use `from google import genai` (never legacy `google-cloud-aiplatform` or `google-generativeai`).
*   **Latest Models**: Always target modern models like `gemini-3-flash-preview` or `gemini-3.1-flash-lite` (legacy `gemini-2.0` and `gemini-1.5` are unsupported for Interactions).
*   **Resource Cleanup**: Always wrap control plane agent creation and data plane interactions in a `try...finally` block to ensure agent resources are deleted on completion or failure, avoiding backend leaks.
*   **Polymorphic Content Handling**: The `extract_text_from_content` helper function safely handles polymorphic content blocks returned by the server, extracting text whether it is returned as a `Content` object (with `.parts`) or a `TextContent` object (with `.text`).
*   **Event-Driven Streaming**: The streaming loop in `code_optimizer.py` listens for `step.delta` events to print text and sandbox execution logs in real-time, which is much simpler and more efficient than polling.
*   **Secure Hybrid MCP**: The platform securely routes tool requests to the specified MCP server and guarantees header confidentiality by only sending custom headers/tokens to that URL.

---

## Developer Tips: Installing Gemini Agent Skills

If you are using an AI coding assistant (like Antigravity) to develop, debug, or extend these examples, you can install the platform's official API skills into your workspace. This equips your AI assistant with deep, up-to-date knowledge of the Control Plane (Managed Agents API) and the Data Plane (Interactions API), helping it write correct code and avoid common pitfalls.

To install the skills in your workspace, run the following commands from your workspace root:

```bash
# Create the local customizations directory if it doesn't exist
mkdir -p .agents/skills

# Clone the official skills repository sparsely
git clone --depth 1 --filter=blob:none --sparse https://github.com/google/skills.git temp_skills_clone
cd temp_skills_clone

# Retrieve the Interactions and Agents API skills
git sparse-checkout set skills/cloud/gemini-interactions-api skills/cloud/gemini-agents-api

# Copy them to your workspace's local .agents/skills directory
cp -r skills/cloud/gemini-interactions-api ../.agents/skills/gemini-interactions-api
cp -r skills/cloud/gemini-agents-api ../.agents/skills/gemini-agents-api

# Clean up the temporary clone
cd ..
rm -rf temp_skills_clone
```

Once installed, your AI assistant will automatically discover and load these skills at the start of your conversations.

