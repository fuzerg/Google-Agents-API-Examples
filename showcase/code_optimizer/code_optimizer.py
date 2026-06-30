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
AGENT_ID = "code-optimizer-showcase"
AGENT_RESOURCE_NAME = f"projects/{project_id}/locations/{LOCATION}/agents/{AGENT_ID}"
BASE_URL = f"https://aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{LOCATION}"

# 2. CONTROL PLANE: CREATE CUSTOM AGENT
def create_custom_agent():
    print(f"Creating custom agent '{AGENT_ID}' (Control Plane)...")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "id": AGENT_ID,
        "base_agent": "antigravity-preview-05-2026", # Recommended base agent container
        "description": "A showcase code optimizer agent with a secure python execution sandbox.",
        "system_instruction": (
            "You are an expert Python performance engineer. Your task is to optimize Python code. "
            "Always write a benchmark using the `timeit` module to measure the execution time of the original code, "
            "run it using your `code_execution` tool, then write and run a benchmark for your optimized version "
            "to prove the speedup. Explain your findings clearly, showing the percentage speedup."
        ),
        "tools": [
            {"type": "code_execution"} # Server-side secure python sandbox
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
    # Case 1: It's a TextContent object (has 'text' attribute)
    if hasattr(content_block, "text"):
        return content_block.text
    # Case 2: It's a standard Content object (has 'parts' attribute)
    if hasattr(content_block, "parts") and content_block.parts:
        return content_block.parts[0].text
    # Case 3: It's a dictionary (fallback)
    if isinstance(content_block, dict):
        if "text" in content_block:
            return content_block["text"]
        if "parts" in content_block and content_block["parts"]:
            part = content_block["parts"][0]
            if isinstance(part, dict):
                return part.get("text")
            return getattr(part, "text", None)
    return None

# 5. MAIN FLOW
def main():
    # Ensure agent is created
    create_custom_agent()
    
    try:
        # Configure SDK client
        os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"
        client = genai.Client(enterprise=True, project=project_id, location=LOCATION)
        
        slow_code = """
def fib(n):
    if n <= 1:
        return n
    return fib(n-1) + fib(n-2)
"""
        
        print("Starting Stateful Streaming Interaction (Data Plane)...")
        print("Submitting code to optimize. The agent will write and run benchmarks in its sandbox...")
        print("--------------------------------------------------------------------------------\n")
        
        # Start a streaming background interaction. The server-side code execution tool will run
        # automatically on the backend, and the agent's thoughts, code, and execution
        # results will stream back to us in real-time.
        response_stream = client.interactions.create(
            agent=AGENT_RESOURCE_NAME,
            input=(
                f"Please optimize this slow Fibonacci function. First, run a benchmark on fib(30) "
                f"to measure its speed. Then, write an optimized version, run a comparative benchmark "
                f"to prove the speedup, and explain the results.\n\nSlow Code:\n{slow_code}"
            ),
            stream=True,
            background=True, # Required for agent interactions
            store=True
        )
        
        # Stream the response events in real-time
        for event in response_stream:
            event_type = getattr(event, "event_type", None)
            if event_type == "step.delta":
                delta = event.delta
                delta_type = getattr(delta, "type", None)
                
                if delta_type == "text":
                    # Stream the model's text output tokens (including code blocks)
                    print(delta.text, end="", flush=True)
                elif delta_type == "code_execution_result":
                    # Stream the sandbox execution outputs!
                    print(delta.result, end="", flush=True)
                            
        print("\n--------------------------------------------------------------------------------")
        print("Interaction finished successfully.")
            
    except Exception as e:
        print(f"An error occurred during interaction: {e}")
    finally:
        # Always clean up the agent resource
        delete_custom_agent()

if __name__ == "__main__":
    main()
