# 1. App Builder

This template demonstrates an Autonomous Agent that acts as a greenfield software engineer. It receives high-level instructions to build a new application, verifies that the application compiles correctly locally, and then pushes the code to a remote repository.

## How the Agent Tests Its Code Locally (Before Pushing!)
While the agent does not have a browser to take visual screenshots of the frontend, we guarantee that the code is functional before it ever reaches GitHub by instructing the agent to run **programmatic verification steps** during the scaffolding phase. 

In `agent.yaml`, the prompt explicitly tells the agent to run:
```bash
npm install
npm run build
npm run lint
```
If the code is broken, `npm run build` will fail. The agent will see this error output directly in its terminal sandbox and can correct the syntax or dependency issues before it commits and pushes to GitHub.

## Understanding the Architecture & Flow

### 1. `prober.py` & Local Execution
Normally, Vertex Agent Engine tools run in an isolated cloud sandbox. However, since the Vertex API (`v1beta1`) does not currently support cancelling long-running tool executions, we had to implement a workaround in `prober.py`:
- `prober.py` intercepts the agent's tool calls (like `run_command`).
- It bypasses the cloud execution by manually running the commands directly on your local workstation (or your CitC workspace).
- Because Vertex restricts appending to interactions stuck in `IN_PROGRESS`, `prober.py` operates statelessly: it bundles the original prompt, the agent's previous text, and the new local tool output, and starts a **brand new** interaction on every loop!

### 2. File Systems & GCSFuse
The agent writes the code to a temporary local folder (`/workspace/local-temp/dashboard`) instead of directly to `/workspace/output`. This is a critical workaround because `/workspace/output` maps to a GCSFuse mount, which lacks `mmap` support and breaks `npm` and `git` operations. Once the agent is done building, testing, and pushing from the local folder, it uses `rsync` to sync the final result over to `/workspace/output`.

### 3. GitHub Authentication
Because the execution was moved locally by `prober.py`, cloud-native secrets injection (like `x-env-secrets`) is bypassed. To authenticate with GitHub, the prompt inside `agent.yaml` is configured with an **explicit Personal Access Token (PAT) URL** (e.g., `https://ghp_YOUR_TOKEN@github.com/...`). This allows the local `git push` command to succeed seamlessly.

## How to Test This Locally

### Option 1: Run the End-to-End Agent Test
You can watch the agent scaffold the app, build it, and push it live by running the prober:
1. Ensure your Virtual Environment is activated:
   ```bash
   cd ~/Google-Agents-API-Examples
   source venv/bin/activate
   ```
2. Run the prober for the App Builder template:
   ```bash
   python3 agent_templates/prober_lifecycle.py agent_templates/nextjs_app_builder
   ```
   *(You will see the agent executing commands in the terminal. When finished, check your remote GitHub repository!)*

### Option 2: Manually Test the Generated Code Locally
Once the agent finishes and syncs the code to the output directory, you can spin up the development server yourself to visually verify the dashboard!

1. Navigate to the synced output directory:
   ```bash
   cd ~/Google-Agents-API-Examples/workspace/output/dashboard
   ```
2. Ensure you are running Node.js version 20 or higher (Next.js requirement). If using `nvm`:
   ```bash
   nvm install 20
   nvm use 20
   ```
3. Install dependencies and start the local development server:
   ```bash
   npm install
   npm run dev
   ```
4. Open your browser and navigate to `http://localhost:3000` to see the results.
