# The Secure Hybrid MCP Support Bot

This example demonstrates how to connect a cloud-hosted agent to an **MCP (Model Context Protocol) server**. This architecture allows the cloud agent to securely invoke custom tools (such as retrieving system hardware metrics) hosted on an external server.

The MCP server is built using the official `mcp` Python SDK's `FastMCP` class and hosted as an **SSE (Server-Sent Events)** application mounted inside **FastAPI**.

We provide two deployment options:
1.  **Local Deployment with Tunneling (ngrok)**: Great for quick local testing on open networks.
2.  **Cloud Deployment with Cloud Run (Private)**: Recommended for restricted or corporate networks (like Google's) where outbound SSH/tunneling tools are blocked. It uses **Service Account Impersonation** to automatically generate OIDC tokens for secure, authenticated communication.

---

## Flow Diagram (Cloud Run Deployment)

```mermaid
sequenceDiagram
    autonumber
    participant Developer as Developer Machine (Client)
    participant CP as Control Plane (GCP REST)
    participant CR as Cloud Run (Private MCP Server)
    participant DP as Data Plane (Interactions API)
    
    Developer->>Developer: Generate OIDC token by impersonating service account
    Developer->>CP: Create Agent "mcp-support-showcase" with 'mcp_server' tool & Auth Header
    CP-->>Developer: Return LRO (Poll until Ready)
    Developer->>DP: Start Background Interaction: "Check my system health"
    Note over DP: Agent decides to call 'local-system-monitor' tool
    DP->>CR: Securely route tool call with Authorization Header
    CR->>CR: Run psutil in container to get CPU, memory, disk metrics
    CR-->>DP: Return metrics payload over SSE/HTTP
    DP-->>Developer: Returns completed interaction status and formatted report
    Developer->>CP: Delete Agent (Cleanup)
```

---

## Option 1: Local Deployment with Tunneling (ngrok)

This option runs the MCP server locally on your machine and exposes it via a public `ngrok` tunnel.

### 1. Start the Local MCP Server
From the `showcase` directory, start the FastAPI server hosting the MCP tool:
```bash
python mcp_support/mcp_server.py
```
The server will start on `http://localhost:8000`, with the SSE connection endpoint at `http://localhost:8000/mcp/sse`.

### 2. Start the secure tunnel (ngrok)
In a **second terminal**, start `ngrok` to expose your local port 8000 to the public internet:
```bash
ngrok http 8000
```

### 3. Configure and run the Client Script
In a **third terminal**, copy the public HTTPS URL forwarded by ngrok (e.g., `https://xxxx.ngrok-free.app`), append `/mcp/sse` to it, set it as an environment variable, and run the client:
```bash
export MCP_SERVER_URL="https://your-tunnel-id.ngrok-free.app/mcp/sse"
python mcp_support/mcp_support.py
```

---

## Option 2: Cloud Deployment with Cloud Run (Private)

This option deploys the MCP server as a private, secure containerized service on Google Cloud Run. The client script will automatically detect the Cloud Run URL, impersonate a service account to generate a short-lived OIDC ID token, and attach it to the agent's tool configuration.

### 1. Setup the Build Service Account (One-time)
Create a dedicated service account and grant it the necessary roles to build and deploy the container. Run these commands from your terminal:

```bash
# Create the service account
gcloud iam service-accounts create mcp-build-sa --display-name="MCP Build Service Account"

# Grant roles to the service account
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:mcp-build-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/cloudbuild.builds.builder"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:mcp-build-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/storage.admin"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:mcp-build-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/artifactregistry.admin"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:mcp-build-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/logging.logWriter"

# Grant yourself permission to impersonate the service account
gcloud iam service-accounts add-iam-policy-binding mcp-build-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
    --member="user:YOUR_EMAIL@example.com" \
    --role="roles/iam.serviceAccountUser"
```
*(Note: Ensure your user account also has the `roles/iam.serviceAccountTokenCreator` role on the project to allow token generation).*

### 2. Deploy the MCP Server to Cloud Run
From the `showcase` directory, deploy the server. This will upload the source, build the image via Cloud Build, and deploy it as a private service:
```bash
gcloud run deploy mcp-server \
    --source mcp_support \
    --region us-central1 \
    --allow-unauthenticated \
    --build-service-account="projects/YOUR_PROJECT_ID/serviceAccounts/mcp-build-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```
*(Note: If your organization policy prevents unauthenticated access, the deployment will succeed but the service will remain private. The client script handles this automatically).*

### 3. Run the Client Script
Copy the **Service URL** outputted by the deployment (e.g., `https://mcp-server-xxx.run.app`), append `/mcp/sse` to it, set it as an environment variable, and run the client:
```bash
export MCP_SERVER_URL="https://mcp-server-xxx.run.app/mcp/sse"
python mcp_support/mcp_support.py
```
The script will automatically fetch the OIDC token via impersonation, register the `mcp_server` tool with the authentication header, run the interaction, and clean up.
