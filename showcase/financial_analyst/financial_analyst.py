import os
import sys
import time
import json
import requests
import subprocess
import google.auth
import google.auth.transport.requests
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

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
AGENT_ID = "financial-analyst-showcase"
AGENT_RESOURCE_NAME = f"projects/{project_id}/locations/{LOCATION}/agents/{AGENT_ID}"
BASE_URL = f"https://aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{LOCATION}"

# GCS Bucket configuration (Overridable via environment variable)
# E.g., export GCS_BUCKET_NAME="my-existing-bucket"
default_bucket_name = f"{project_id}-agent-skills"
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", default_bucket_name)
BUCKET_URL = f"gs://{BUCKET_NAME}"

# Resolve paths relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SKILL_DIR = os.path.join(SCRIPT_DIR, "skills", "financial_analyst")

# 2. AUTOMATED GCS PROVISIONING & SKILL UPLOAD
def provision_gcs_and_upload_skill():
    # Resolve local SDK paths if available in the workspace to bypass PATH issues
    # SCRIPT_DIR is showcase/financial_analyst, so workspace_dir is two levels up
    workspace_dir = os.path.dirname(os.path.dirname(SCRIPT_DIR))
    sdk_bin_dir = os.path.join(workspace_dir, "google-cloud-sdk", "bin")
    gcloud_path = os.path.join(sdk_bin_dir, "gcloud")
    gsutil_path = os.path.join(sdk_bin_dir, "gsutil")
    
    gcloud_cmd = gcloud_path if os.path.exists(gcloud_path) else "gcloud"
    gsutil_cmd = gsutil_path if os.path.exists(gsutil_path) else "gsutil"
    
    # If using a custom user-supplied bucket, we assume it already exists and skip creation
    if BUCKET_NAME != default_bucket_name:
        print(f"\nUsing user-supplied GCS bucket: {BUCKET_URL} (skipping creation check)")
    else:
        print(f"\nChecking if GCS bucket '{BUCKET_URL}' exists...")
        # Check if bucket exists using gcloud storage
        result = subprocess.run([gcloud_cmd, "storage", "buckets", "describe", BUCKET_URL], capture_output=True)
        if result.returncode != 0:
            print(f"Bucket '{BUCKET_URL}' does not exist. Creating it...")
            # Create the bucket
            create_result = subprocess.run(
                [gcloud_cmd, "storage", "buckets", "create", BUCKET_URL, "--location=us"],
                capture_output=True,
                text=True
            )
            if create_result.returncode != 0:
                print("\n=====================================================================")
                print(f"ERROR: Failed to create GCS bucket: {create_result.stderr.strip()}")
                print("If you do not have permissions to create buckets in this project, you can:")
                print("1. Use an existing bucket you own: export GCS_BUCKET_NAME=\"your-bucket-name\"")
                print("2. Ask your admin to grant your account the 'Storage Admin' role.")
                print("=====================================================================\n")
                sys.exit(1)
            print("Bucket created successfully.")
        else:
            print("Bucket already exists.")
        
    print(f"Uploading custom skill files from '{LOCAL_SKILL_DIR}' to {BUCKET_URL}/financial_analyst...")
    # Upload the skill directory
    upload_result = subprocess.run(
        [gcloud_cmd, "storage", "cp", "-r", LOCAL_SKILL_DIR, f"{BUCKET_URL}/"],
        capture_output=True,
        text=True
    )
    if upload_result.returncode != 0:
        print(f"Failed to upload skill files to GCS: {upload_result.stderr}")
        sys.exit(1)
    print("Skill files uploaded successfully to GCS.\n")

# 3. CONTROL PLANE: CREATE CUSTOM AGENT WITH GCS SKILL
def create_custom_agent():
    print(f"Creating custom agent '{AGENT_ID}' with GCS-mounted skill (Control Plane)...")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # Define the payload mounting our GCS skill and enabling tools/network
    payload = {
        "id": AGENT_ID,
        "base_agent": "antigravity-preview-05-2026", # Recommended base agent container
        "description": "A showcase financial analyst agent with GCS-mounted stock and PDF tools.",
        "system_instruction": (
            "You are a professional financial analyst. Your goal is to analyze financial assets, "
            "research recent news, perform stock analysis, and generate comprehensive PDF reports. "
            "You have custom skills mounted in `/workspace/skills/`. You must read and follow the "
            "instructions in the SKILL.md files within your skills to understand how to use the "
            "provided helper tools and how to format and return your outputs (such as generating "
            "and streaming PDF reports)."
        ),
        "tools": [
            {"type": "google_search"}, # Server-side search tool for news
            {"type": "code_execution"}  # Required to execute our custom python helpers!
        ],
        "base_environment": {
            "type": "remote",
            "sources": [
                {
                    "type": "gcs",
                    "source": f"{BUCKET_URL}/financial_analyst", # Mount the skill from GCS
                    "target": "/workspace/skills/financial_analyst" # Target path in container
                }
            ],
            "network": {
                "allowlist": [
                    { "domain": "*" } # Allow outbound requests to Yahoo Finance & pip
                ]
            }
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

# 4. CONTROL PLANE: DELETE CUSTOM AGENT
def delete_custom_agent():
    print(f"\nCleaning up: Deleting custom agent '{AGENT_ID}' (Control Plane)...")
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.delete(f"{BASE_URL}/agents/{AGENT_ID}", headers=headers)
    if response.status_code == 200:
        print("Agent deleted successfully.")
    else:
        print(f"Failed to delete agent: {response.text}")

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

# 6. HELPER TO SAFELY EXTRACT TEXT FROM POLYMORPHIC CONTENT
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

# 7. MAIN FLOW
def main():
    # Step 1: Provision GCS and upload the custom skill (exits if creation fails and no custom bucket is set)
    provision_gcs_and_upload_skill()
    
    # Step 2: Create the custom agent mounting the GCS skill
    create_custom_agent()
    
    try:
        # Configure SDK client
        os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"
        client = genai.Client(enterprise=True, project=project_id, location=LOCATION)
        
        print("Starting Turn 1 (Data Plane)...")
        print("Submitting request. The agent will run the GCS skill, scrape Yahoo Finance, and write the PDF...")
        
        # Start the background interaction
        # We ask the agent to use the GCS-mounted stock_helper and pdf_helper.
        turn1 = client.interactions.create(
            agent=AGENT_RESOURCE_NAME,
            input="Compare GOOG and MSFT. Research their recent news, analyze their stock performance, and generate the PDF report.",
            background=True,
            store=True,
            timeout=120 # Increase client-side timeout for container cold-start
        )
        
        # Poll until the background task completes
        turn1 = wait_for_interaction(client, turn1)
        
        # Print the clean raw text response from the model (excluding the base64 stream)
        print("\n================ RAW RESPONSE ==================")
        model_texts = []
        for step in turn1.steps:
            if getattr(step, "type", None) == "model_output":
                if getattr(step, "content", None) and step.content:
                    t = extract_text_from_content(step.content[0])
                    if t:
                        model_texts.append(t)
        raw_response = "".join(model_texts)
        print(raw_response)
        print("================================================")
        
        # Step 3: Extract and save the PDF locally by searching ALL steps (including tool outputs)
        pdf_b64 = None
        for step in turn1.steps:
            step_text = ""
            # Extract text from content blocks (where sandbox stdout is stored)
            if getattr(step, "content", None):
                for content_block in step.content:
                    t = extract_text_from_content(content_block)
                    if t:
                        step_text += t
            # Also check for direct text/output attributes to be safe
            for attr in ["text", "output", "result"]:
                if hasattr(step, attr) and getattr(step, attr):
                    step_text += str(getattr(step, attr))
                    
            if "__PDF_START__" in step_text and "__PDF_END__" in step_text:
                start_idx = step_text.find("__PDF_START__") + len("__PDF_START__")
                end_idx = step_text.find("__PDF_END__")
                candidate = step_text[start_idx:end_idx].strip()
                if len(candidate) > 100: # Ensure it's the real base64 stream, not a text mention
                    pdf_b64 = candidate
                    break
                    
        if pdf_b64:
            print("\nPDF report markers detected in history! Extracting and saving PDF...")
            try:
                import base64
                # Clean up any literal escaped newlines (\\n, \\r) and actual whitespaces/newlines
                clean_b64 = pdf_b64.replace("\\n", "").replace("\\r", "")
                clean_b64 = "".join(clean_b64.split())
                # Fix padding if missing
                pad = len(clean_b64) % 4
                if pad:
                    clean_b64 += "=" * (4 - pad)
                    
                pdf_data = base64.b64decode(clean_b64)
                output_pdf_path = os.path.join(SCRIPT_DIR, "financial_report.pdf")
                with open(output_pdf_path, "wb") as f:
                    f.write(pdf_data)
                print(f"\n✨ Success! Beautiful PDF report saved locally to: {output_pdf_path}")
            except Exception as pdf_err:
                print(f"Failed to decode and save PDF: {pdf_err}")
        else:
            print("\n[Warning] No PDF markers found in the interaction history. The agent may have failed to generate the PDF.")
            
    except Exception as e:
        print(f"An error occurred during interaction: {e}")
    finally:
        # Always clean up the agent resource
        delete_custom_agent()

if __name__ == "__main__":
    main()
