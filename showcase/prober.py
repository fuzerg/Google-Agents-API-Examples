#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import sys
import time
import re
import yaml
import uuid
import json
import base64
import subprocess
import requests
import google.auth
import google.auth.transport.requests
from google import genai

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 prober.py <template_dir> [prompt]")
        sys.exit(1)
        
    template_dir = sys.argv[1].rstrip('/')
    template_name = os.path.basename(template_dir)
    if not os.path.isdir(template_dir):
        print(f"Error: Directory '{template_dir}' not found.")
        sys.exit(1)
        
    agent_yaml_path = os.path.join(template_dir, 'agent.yaml')
    if not os.path.exists(agent_yaml_path):
        print(f"Error: agent.yaml not found in {template_dir}")
        sys.exit(1)
        
    # 1. Resolve GCP Authentication & Project
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
        print("GCP Project ID could not be resolved. Please run: gcloud config set project <PROJECT_ID>")
        sys.exit(1)
        
    print(f"Using GCP Project: {project_id}")
    
    # 2. Resolve Environment Variables & Config
    gcs_bucket = os.environ.get("GCS_BUCKET_NAME", f"{project_id}-agent-skills")
    os.environ["GCS_BUCKET"] = gcs_bucket
    
    mcp_url = os.environ.get("MCP_SERVER_URL")
    if mcp_url:
        if not mcp_url.endswith("/sse") and not mcp_url.endswith("/sse/"):
            mcp_url = mcp_url.rstrip("/") + "/sse"
        os.environ["MCP_SERVER_URL"] = mcp_url


    
    with open(agent_yaml_path, 'r') as f:
        content = f.read()
        
    # Expand environment variables like ${VAR} or $VAR
    def replace_env_var(match):
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, match.group(0))
        
    expanded_content = re.sub(r'\$\{(\w+)\}|\$(\w+)', replace_env_var, content)
    config = yaml.safe_load(expanded_content)
    
    agent_id = f"{config.get('id')}-{uuid.uuid4().hex[:8]}"
    base_agent = config.get('base_agent', 'antigravity-preview-05-2026')
    description = config.get('description', '')
    tools = config.get('tools', [])
    env_config = config.get('environment', {})
    
    # Extract system instruction (prioritize AGENTS.md if it exists)
    system_instruction = config.get('instructions')
    agents_md_path = os.path.join(template_dir, 'AGENTS.md')
    if os.path.exists(agents_md_path):
        with open(agents_md_path, 'r') as f:
            system_instruction = f.read()
            
    # 3. Handle Skill Upload to GCS if needed
    local_skills_dir = os.path.join(template_dir, 'skills')
    if os.path.exists(local_skills_dir):
        
        # Generic Secret Injection: If agent.yaml defines x-env-secrets, inject them into skill .env files
        secrets_config = config.get("x-env-secrets", {})
        created_env_files = []
        for skill_name, secrets in secrets_config.items():
            skill_dir = os.path.join(local_skills_dir, skill_name)
            if os.path.exists(skill_dir):
                env_path = os.path.join(skill_dir, '.env')
                with open(env_path, 'w') as f:
                    for secret in secrets:
                        val = os.environ.get(secret, "")
                        f.write(f'{secret}="{val}"\n')
                created_env_files.append(env_path)
                
        try:
            for skill_name in os.listdir(local_skills_dir):
                skill_path = os.path.join(local_skills_dir, skill_name)
                if os.path.isdir(skill_path):
                    # Ensure bucket exists
                    gcloud_cmd = "gcloud"
                    bucket_url = f"gs://{gcs_bucket}"
                    print(f"Checking GCS bucket {bucket_url}...")
                    res = subprocess.run([gcloud_cmd, "storage", "buckets", "describe", bucket_url], capture_output=True)
                    if res.returncode != 0:
                        print(f"Creating GCS bucket {bucket_url}...")
                        subprocess.run([gcloud_cmd, "storage", "buckets", "create", bucket_url, "--location=us"], check=True)
                    
                    print(f"Uploading skill files from '{skill_path}' to {bucket_url}/{skill_name}...")
                    subprocess.run([gcloud_cmd, "storage", "cp", "-r", skill_path, f"{bucket_url}/"], check=True)
        finally:
            for env_file in created_env_files:
                if os.path.exists(env_file):
                    os.remove(env_file)

    # 4. Control Plane: Register custom agent on Vertex AI
    LOCATION = "global"
    BASE_URL = f"https://aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{LOCATION}"
    AGENT_RESOURCE_NAME = f"projects/{project_id}/locations/{LOCATION}/agents/{agent_id}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    agent_payload = {
        "id": agent_id,
        "base_agent": base_agent,
        "description": description,
        "system_instruction": system_instruction,
        "tools": tools,
        "base_environment": {
            "type": env_config.get('type', 'remote'),
            "sources": env_config.get('sources', []),
        }
    }
    if 'network' in env_config:
        agent_payload["base_environment"]["network"] = env_config["network"]
        
    print(f"Registering custom agent '{agent_id}' via Control Plane...")
    response = requests.post(f"{BASE_URL}/agents", headers=headers, json=agent_payload)
    if response.status_code != 200 and response.status_code != 409:
        raise Exception(f"Failed to create agent: {response.text}")
        
    if response.status_code == 409:
        print(f"Agent '{agent_id}' already exists. Re-using existing agent.\n")
    else:
        operation = response.json()
        operation_name = operation["name"]
        print("Waiting for agent registration to complete...")
        while True:
            poll_resp = requests.get(f"https://aiplatform.googleapis.com/v1beta1/{operation_name}", headers=headers)
            poll_data = poll_resp.json()
            if poll_data.get("done"):
                if "error" in poll_data:
                    raise Exception(f"Agent registration failed: {poll_data['error']}")
                print("Agent registered successfully and is ready!\n")
                break
            time.sleep(3)
            
    # 5. Data Plane: Start Stateful Streaming Interaction
    try:
        # Determine prompt input
        examples = config.get('examples', [])
        if len(sys.argv) > 2:
            prompts = [sys.argv[2]]
        elif examples:
            prompts = [ex.get('prompt') for ex in examples if ex.get('prompt')]
        else:
            prompts = ["Hello"]
        
        # Initialize Google Gen AI client with Enterprise credentials
        os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"
        client = genai.Client(enterprise=True, project=project_id, location=LOCATION)
        
        log_content = ""
        for i, prompt in enumerate(prompts):
            print(f"Starting Stateful Streaming Interaction (Data Plane) - Run {i+1}/{len(prompts)}...")
            print(f"Prompt: {prompt}")
            print("--------------------------------------------------------------------------------\n")
            
            response_stream = client.interactions.create(
                agent=AGENT_RESOURCE_NAME,
                input=prompt,
                stream=True,
                background=True,
                store=True,
                timeout=300
            )

            for event in response_stream:
                event_type = getattr(event, "event_type", None)
                if event_type == "step.delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text":
                        print(delta.text, end="", flush=True)
                        log_content += delta.text
                    elif delta_type == "code_execution_result":
                        print(delta.result, end="", flush=True)
                        log_content += delta.result
                        
            print("\n--------------------------------------------------------------------------------")
            print(f"Interaction {i+1} finished successfully.\n")
        
        # 6. Post-processing
        # 6. Post-processing: Download requested output paths
        download_targets = config.get("x-download-outputs", ["/workspace/output"])
        sources = config.get("environment", {}).get("sources", [])
        for source in sources:
            if source.get("type") == "gcs" and source.get("target") in download_targets:
                output_gcs_path = source.get("source")
                target_name = os.path.basename(source.get("target").rstrip('/'))
                local_output_dir = os.path.join(template_dir, target_name)
                os.makedirs(local_output_dir, exist_ok=True)
                
                print(f"\nDownloading output files from Google Cloud Storage mount...")
                print(f"Source: {output_gcs_path}/*")
                print(f"Target: {local_output_dir}")
                
                # Wait 3 seconds for GCS Fuse background flush/sync to complete
                time.sleep(3)
                
                # Copy all files from GCS output path recursively
                res = subprocess.run(["gcloud", "storage", "cp", "-r", f"{output_gcs_path}/*", local_output_dir], capture_output=True, text=True)
                if res.returncode == 0:
                    print(f"✨ Output files downloaded and saved locally to: {local_output_dir}")
                else:
                    print(f"Warning: Failed to download output files from GCS: {res.stderr}")

        # Extract and print custom messages defined in agent.yaml
        extract_msgs = config.get("x-extract-messages", [
            {"start": "__PR_URL_START__", "end": "__PR_URL_END__", "message": "Automated Pull Request created successfully: {}"}
        ])
        for ext in extract_msgs:
            start_marker = ext.get("start")
            end_marker = ext.get("end")
            msg_template = ext.get("message", "Extracted: {}")
            if start_marker in log_content and end_marker in log_content:
                start_idx = log_content.find(start_marker) + len(start_marker)
                end_idx = log_content.find(end_marker, start_idx)
                if end_idx > start_idx:
                    extracted_value = log_content[start_idx:end_idx].strip()
                    print(f"\n✨ {msg_template.format(extracted_value)}")

                
    except Exception as e:
        print(f"An error occurred during interaction: {e}")
    finally:
        # 7. Control Plane Resource Cleanup
        print(f"\nCleaning up: Deleting agent '{agent_id}' (Control Plane)...")
        cleanup_resp = requests.delete(f"{BASE_URL}/agents/{agent_id}", headers=headers)
        if cleanup_resp.status_code == 200:
            print("Agent deleted successfully.")
        else:
            print(f"Failed to delete agent resource: {cleanup_resp.text}")

if __name__ == "__main__":
    main()
