import os
import sys
import time
import requests
import google.auth
import google.auth.transport.requests
from google import genai

# =====================================================================
# MANDATORY SDK & MODEL WARNINGS (As required by Gemini platform guidelines)
# =====================================================================
print("=====================================================================")
print("WARNING: Legacy packages like 'google-cloud-aiplatform' or")
print("'google-generativeai' are strictly unsupported for the Interactions API.")
print("You MUST use the unified Google Gen AI SDK ('google-genai >= 2.0.0').")
print("---------------------------------------------------------------------")
print("WARNING: Legacy models like 'gemini-2.0' or 'gemini-1.5' are deprecated")
print("and unsupported for the Interactions API. You must use latest models")
print("like 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', or 'gemini-2.5'.")
print("=====================================================================\n")

# 1. AUTHENTICATION & SETUP
# Retrieve Application Default Credentials (ADC)
try:
    credentials, project_id = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    access_token = credentials.token
except Exception as e:
    print(f"Authentication failed: {e}")
    print("Please run: gcloud auth application-default login")
    sys.exit(1)

if not project_id:
    print("GCP Project ID could not be resolved. Please set your project using:")
    print("gcloud config set project agents-api-eval-143444")
    sys.exit(1)

print(f"Using GCP Project: {project_id}")

# Configuration
LOCATION = "global"
AGENT_ID = "mcp-support-showcase"
AGENT_RESOURCE_NAME = f"projects/{project_id}/locations/{LOCATION}/agents/{AGENT_ID}"
BASE_URL = f"https://aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{LOCATION}"

# Retrieve the MCP Server Tunnel URL from environment
mcp_url = os.environ.get("MCP_SERVER_URL")
if not mcp_url:
    print("\nError: MCP_SERVER_URL environment variable is not set.")
    print("To run this example:")
    print("1. Start the local MCP server: venv/bin/python mcp_support/mcp_server.py")
    print("2. Start ngrok tunnel:         ngrok http 8000")
    print("3. Set the public HTTPS URL:   export MCP_SERVER_URL=\"https://xxxx.ngrok-free.app/mcp/sse\"")
    print("4. Run this script again.")
    sys.exit(1)

# Ensure the URL points to the SSE endpoint
if not mcp_url.endswith("/mcp/sse") and not mcp_url.endswith("/mcp/sse/"):
    # Append the standard SSE path if the user only provided the base tunnel URL
    mcp_url = mcp_url.rstrip("/") + "/mcp/sse"

print(f"Registering MCP Server Tool at: {mcp_url}")

# 2. CONTROL PLANE: CREATE CUSTOM AGENT WITH MCP TOOL
def create_custom_agent():
    print(f"Creating custom agent '{AGENT_ID}' with MCP tool (Control Plane)...")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # Define the MCP tool pointing to our public tunnel.
    # The platform will securely route tool calls to this URL.
    mcp_tool = {
        "type": "mcp",
        "name": "local-system-monitor",
        "url": mcp_url
    }
    
    payload = {
        "id": AGENT_ID,
        "base_agent": "antigravity-preview-05-2026", # Recommended base agent container
        "description": "A showcase support agent connected to a local machine via MCP.",
        "system_instruction": (
            "You are a helpful IT support assistant. Your task is to check the user's local machine health. "
            "Use your `local-system-monitor` tool to retrieve the system metrics, analyze the CPU, memory, "
            "and disk usage, and provide a clear, professional system health report. Highlight any potential "
            "bottlenecks or issues."
        ),
        "tools": [
            mcp_tool # Register the MCP server tool
        ],
        "base_environment": {
            "type": "remote" # Required remote container environment
        }
    }
    
    response = requests.post(f"{BASE_URL}/agents", headers=headers, json=payload)
    if response.status_code == 409:
        print(f"Agent '{AGENT_ID}' already exists. Using the existing agent.\n")
        return
    if response.status_code != 200:
        raise Exception(f"Failed to create agent: {response.text}")
    
    operation = response.json()
    operation_name = operation["name"]
    print(f"Agent creation started. Operation: {operation_name}")
    
    # Poll the Long-Running Operation (LRO)
    while True:
        print("Polling agent creation status...")
        poll_resp = requests.get(f"https://aiplatform.googleapis.com/v1beta1/{operation_name}", headers=headers)
        poll_data = poll_resp.json()
        if poll_data.get("done"):
            if "error" in poll_data:
                raise Exception(f"Agent creation failed: {poll_data['error']}")
            print("Agent created successfully and is ready!\n")
            break
        time.sleep(5)

# 3. CONTROL PLANE: DELETE CUSTOM AGENT
def delete_custom_agent():
    print(f"\nCleaning up: Deleting custom agent '{AGENT_ID}' (Control Plane)...")
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.delete(f"{BASE_URL}/agents/{AGENT_ID}", headers=headers)
    if response.status_code == 200:
        print("Agent deleted successfully.")
    else:
        print(f"Failed to delete agent: {response.text}")

# 4. HELPER TO SAFELY EXTRACT TEXT FROM POLYMORPHIC CONTENT
def extract_text_from_content(content_block):
    if not content_block:
        return None
    if hasattr(content_block, "text"):
        return content_block.text
    if hasattr(content_block, "parts") and content_block.parts:
        return content_block.parts[0].text
    if isinstance(content_block, dict):
        if "text" in content_block:
            return content_block["text"]
        if "parts" in content_block and content_block["parts"]:
            part = content_block["parts"][0]
            if isinstance(part, dict):
                return part.get("text")
            return getattr(part, "text", None)
    return None

# 5. POLLING HELPER FOR BACKGROUND INTERACTIONS
def wait_for_interaction(client, interaction):
    print(f"Waiting for interaction {interaction.id} to complete...")
    while True:
        interaction = client.interactions.get(id=interaction.id)
        print(f"Current status: {interaction.status}")
        
        if interaction.status in ["completed", "failed", "cancelled"]:
            if interaction.status == "failed":
                raise Exception(f"Interaction failed: {interaction}")
            print(f"Interaction {interaction.id} completed successfully.")
            return interaction
        time.sleep(5)

# 6. MAIN FLOW
def main():
    # Ensure agent is created
    create_custom_agent()
    
    try:
        # Configure SDK client
        os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"
        client = genai.Client(enterprise=True, project=project_id, location=LOCATION)
        
        print("Starting Turn 1 (Data Plane)...")
        print("Submitting request. The cloud agent will call your local MCP server via the secure tunnel...")
        
        # Start the background interaction
        turn1 = client.interactions.create(
            agent=AGENT_RESOURCE_NAME,
            input=(
                "Please check my local system metrics using your local-system-monitor tool. "
                "Analyze the CPU, memory, and disk usage, and provide a professional system health report."
            ),
            background=True, # Required for agent interactions
            store=True
        )
        
        # Poll until the background task completes
        # The agent will call the MCP tool autonomously in the background.
        turn1 = wait_for_interaction(client, turn1)
        
        # Concatenate text from all model_output steps (since the response is split into chunks)
        response_chunks = []
        for step in turn1.steps:
            if getattr(step, "type", None) == "model_output":
                if getattr(step, "content", None) and step.content:
                    chunk_text = extract_text_from_content(step.content[0])
                    if chunk_text:
                        response_chunks.append(chunk_text)
                        
        final_text = "".join(response_chunks)
        
        print("\n================ SYSTEM HEALTH REPORT ================")
        if final_text:
            print(final_text)
        else:
            print("[Error] No text response returned by the agent.")
        print("======================================================")
            
    except Exception as e:
        print(f"An error occurred during interaction: {e}")
    finally:
        # Always clean up the agent resource
        delete_custom_agent()

if __name__ == "__main__":
    main()
