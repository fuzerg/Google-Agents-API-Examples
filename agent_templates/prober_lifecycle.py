import re
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
import logging

logging.basicConfig(level=logging.DEBUG)
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
from google.cloud import storage

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
        config = yaml.safe_load(os.path.expandvars(f.read()))
    
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
            print(f"Checking GCS bucket gs://{gcs_bucket}...")
            storage_client = storage.Client(project=project_id, credentials=credentials)
            bucket = storage_client.bucket(gcs_bucket)
            if not bucket.exists():
                print(f"Creating GCS bucket gs://{gcs_bucket}...")
                bucket.create(location="us")

            for skill_name in os.listdir(local_skills_dir):
                skill_path = os.path.join(local_skills_dir, skill_name)
                if os.path.isdir(skill_path):
                    print(f"Uploading skill files from '{skill_path}' to gs://{gcs_bucket}/{skill_name}...")
                    for root, _, files in os.walk(skill_path):
                        for file in files:
                            local_file = os.path.join(root, file)
                            rel_path = os.path.relpath(local_file, skill_path)
                            blob_name = f"{skill_name}/{rel_path}".replace("\\", "/")
                            blob = bucket.blob(blob_name)
                            blob.upload_from_filename(local_file)

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
        "tools": tools
    }
        
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
        examples_config = config.get('examples', [])
        if len(sys.argv) > 2:
            examples = [{"title": "manual_run", "prompt": sys.argv[2]}]
        elif examples_config:
            examples = examples_config
        else:
            examples = [{"title": "default_run", "prompt": "Hello"}]
        
        # Initialize Google Gen AI client with Enterprise credentials
        os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"
        client = genai.Client(enterprise=True, project=project_id, location=LOCATION)
        
        import copy
        for i, example in enumerate(examples):
            prompt = example.get('prompt', 'Hello')
            example_title = example.get('title', f"example_{i}")
            safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', example_title).lower()
            
            # Prepare interaction-specific environment if output_mount is present
            output_mount = config.get("x-output-mount")
            interaction_environment = None
            if env_config:
                sources = copy.deepcopy(env_config.get('sources', []))
                if output_mount:
                    # Create a unique GCS folder for this example
                    example_gcs_output = f"gs://{gcs_bucket}/output_{agent_id}_{safe_title}"
                    sources.append({
                        "type": "gcs",
                        "source": example_gcs_output,
                        "target": output_mount
                    })
                interaction_environment = {
                    "type": env_config.get('type', 'remote'),
                    "sources": sources,
                }
                if 'network' in env_config:
                    interaction_environment["network"] = env_config["network"]

            log_content = ""
            print(f"Starting Stateful Streaming Interaction (Data Plane) - Run {i+1}/{len(examples)}...")
            print(f"Prompt: {prompt}")
            print("--------------------------------------------------------------------------------\n")
            
            try:
                # Setup kwargs for interaction create
                create_kwargs = {
                    "agent": AGENT_RESOURCE_NAME,
                    "input": prompt,
                    "stream": True,
                    "background": True,
                    "store": True,
                    "timeout": 900
                }
                if interaction_environment:
                    create_kwargs["environment"] = interaction_environment
                    
                interaction_id = None
                
                while True:
                    import time as _time
                    _time.sleep(2)
                    
                    max_retries = 5
                    for attempt in range(max_retries):
                        try:
                            # Refresh credentials to prevent 1-hour expiration on long tasks
                            auth_req = google.auth.transport.requests.Request()
                            credentials.refresh(auth_req)
                            # Re-instantiate client to ensure it picks up the refreshed token
                            client = genai.Client(enterprise=True, project=project_id, location=LOCATION)
                            
                            response_stream = client.interactions.create(**create_kwargs)
                            # Actually, we need to try to consume the first event to trigger the 429
                            response_iter = iter(response_stream)
                            try:
                                first_event = next(response_iter)
                            except StopIteration:
                                first_event = None
                            break
                        except Exception as e:
                            if "429" in str(e) or "quota" in str(e).lower():
                                delay = 2 ** attempt * 10
                                print(f"[!] Hit quota limit (429). Retrying in {delay} seconds... (Attempt {attempt+1}/{max_retries})")
                                _time.sleep(delay)
                                if attempt == max_retries - 1:
                                    raise
                            else:
                                raise

                    pending_tool_calls = []
                    step_log_content = ""

                    try:
                        # Process first event if it exists
                        import itertools
                        if first_event:
                            events = itertools.chain([first_event], response_iter)
                        else:
                            events = []
                        for event in events:
                            event_type = getattr(event, "event_type", None)
                            print(f"\n[DEBUG EVENT TYPE]: {event_type}", flush=True)
                            if event_type == "interaction.created":
                                if not interaction_id:
                                    interaction_id = getattr(event.interaction, "id", None)
                                
                            if event_type == "step.start":
                                step = getattr(event, "step", None)
                                current_step_type = getattr(step, "type", None)
                                if current_step_type in ("function_call", "tool_call", "mcp_server_tool_call"):
                                    current_step_id = getattr(step, "id", getattr(step, "call_id", None))
                                    if not current_step_id and hasattr(step, "model_dump"):
                                        dumped = step.model_dump()
                                        current_step_id = dumped.get("id", dumped.get("call_id"))
                                    pending_tool_calls.append({
                                        "id": current_step_id,
                                        "name": getattr(step, "name", None),
                                        "args": ""
                                    })
                                
                            if event_type == "error":
                                print(f"\n[DEBUG] Error occurred: {dir(event)} {vars(event) if hasattr(event, '__dict__') else event}", flush=True)

                            if event_type == "step.delta":
                                delta = getattr(event, "delta", None)
                                delta_type = getattr(delta, "type", None)
                                print(f"[DEBUG DELTA TYPE]: {delta_type}", flush=True)
                                
                                if delta_type == "text":
                                    print(delta.text, end="", flush=True)
                                    log_content += delta.text
                                    step_log_content += delta.text
                                elif delta_type == "code_execution_result":
                                    print(delta.result, end="", flush=True)
                                    log_content += delta.result
                                elif delta_type == "arguments_delta":
                                    args_chunk = getattr(delta, "arguments", "")
                                    print(f"[DEBUG DELTA TYPE]: arguments_delta, args_chunk: {args_chunk[:20]}...", flush=True)
                                    if args_chunk and pending_tool_calls:
                                        pending_tool_calls[-1]["args"] += args_chunk
                                        try:
                                            import json
                                            json.loads(pending_tool_calls[-1]["args"])
                                            print("[DEBUG] Tool call JSON fully formed! Breaking stream to bypass native execution.")
                                            if interaction_id:
                                                short_id = interaction_id.split("/")[-1] if isinstance(interaction_id, str) else interaction_id
                                                print(f"[DEBUG] Canceling interaction {short_id} to stop native execution.")
                                                try:
                                                    cancel_headers = {
                                                        "Authorization": f"Bearer {credentials.token}",
                                                        "x-goog-user-project": project_id
                                                    }
                                                    cancel_url = f"{BASE_URL}/interactions/{short_id}/cancel"
                                                    resp = requests.post(cancel_url, headers=cancel_headers)
                                                    print(f"[DEBUG] Cancel response: {resp.status_code} - {resp.text}")
                                                except Exception as ce:
                                                    print(f"[DEBUG] Cancel error: {ce}")
                                            break
                                        except Exception:
                                            pass
                                        
                    except StopIteration:
                        pass
                        
                    # Skip polling since cancel is 501 unimplemented
                    
                    
                    if not pending_tool_calls:
                        print("\n--------------------------------------------------------------------------------")
                        print(f"Interaction {i+1} finished successfully.\n")
                        break
                    
                    import json
                    import subprocess
                    
                    text_payload = ""
                    for tool_call in pending_tool_calls:
                        current_tool_name = tool_call["name"]
                        current_tool_args = tool_call["args"]
                        print(f"\n\n[!] Executing tool call locally: {current_tool_name}")
                        
                        try:
                            args_dict = json.loads(current_tool_args)
                        except Exception as e:
                            args_dict = {}
                            
                        tool_output = ""
                        if current_tool_name == "run_command":
                            cmd = args_dict.get("CommandLine", args_dict.get("command", ""))
                            cwd = args_dict.get("Cwd", "/workspace")
                            if cwd.startswith("/workspace"):
                                cwd = cwd.replace("/workspace", "/tmp/agent-workspace")
                            cmd = cmd.replace("/workspace", "/tmp/agent-workspace")
                            if "/skills/" in cmd:
                                cmd = cmd.replace("/skills/", os.path.abspath(os.path.join(template_dir, "skills")) + "/")
                            print(f"--> CMD: {cmd}\n--> CWD: {cwd}")
                            try:
                                # Create directory if it doesn't exist to prevent crash
                                os.makedirs(cwd, exist_ok=True)
                                proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120)
                                tool_output = proc.stdout
                                if proc.stderr:
                                    tool_output += "\nSTDERR:\n" + proc.stderr
                                if len(tool_output) > 4000:
                                    tool_output = "...[TRUNCATED BY PROBER]...\n" + tool_output[-4000:]
                                print(f"[!] Command output ({len(tool_output)} chars)")
                            except Exception as e:
                                tool_output = f"Error executing command locally: {e}"
                                print(f"[!] Error: {e}")
                        else:
                            tool_output = f"Tool {current_tool_name} not implemented locally."
                            print(f"[!] Not executing {current_tool_name}")
                            
                        text_payload += f"The tool `{current_tool_name}` was executed locally by the testing harness and returned the following output:\n{tool_output}\n\n"
                    
                    # Accumulate history properly for subsequent turns to avoid exponential string growth
                    prompt += f"\n\n--- TURN {i+1} ---\nAgent output so far:\n{step_log_content}\n\nTool Results:\n{text_payload}\n\nPlease continue the task."
                    
                    create_kwargs = {
                        "agent": AGENT_RESOURCE_NAME,
                        "input": [{"text": prompt}],
                        "stream": True,
                        "background": True,
                        "store": True,
                        "timeout": 900
                    }
                    if interaction_environment:
                        create_kwargs["environment"] = interaction_environment
            
                # Download output path
                if output_mount:
                    target_name = os.path.basename(output_mount.rstrip('/'))
                    local_output_dir = os.path.join(template_dir, f"{target_name}_{safe_title}")
                    os.makedirs(local_output_dir, exist_ok=True)
                    
                    print(f"\nDownloading output files from Google Cloud Storage mount...")
                    print(f"Source: {example_gcs_output}/*")
                    print(f"Target: {local_output_dir}")
                    
                    time.sleep(3)
                    
                    try:
                        gs_path = example_gcs_output.replace("gs://", "")
                        bucket_name = gs_path.split("/")[0]
                        prefix = gs_path[len(bucket_name)+1:] + "/"
                        
                        storage_client = storage.Client(project=project_id, credentials=credentials)
                        bucket = storage_client.bucket(bucket_name)
                        blobs = bucket.list_blobs(prefix=prefix)
                        
                        downloaded_count = 0
                        for blob in blobs:
                            if blob.name.endswith("/"):
                                continue
                            rel_path = blob.name[len(prefix):]
                            local_file_path = os.path.join(local_output_dir, rel_path)
                            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                            blob.download_to_filename(local_file_path)
                            downloaded_count += 1
                            
                        if downloaded_count > 0:
                            print(f"✨ Output files downloaded and saved locally to: {local_output_dir}")
                        else:
                            print(f"Warning: No output files found in GCS.")
                    except Exception as e:
                        print(f"Warning: Failed to download output files from GCS: {str(e)}")

                # Extract and print custom messages defined in agent.yaml
                extract_msgs = config.get("x-extract-messages", [])
                if extract_msgs:
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
                print(f"An error occurred during interaction {i+1}: {e}")
                
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # 7. Control Plane Resource Cleanup
        print(f"\nCleaning up: Deleting agent '{agent_id}' (Control Plane)...")
        credentials.refresh(auth_req)
        headers["Authorization"] = f"Bearer {credentials.token}"
        cleanup_resp = requests.delete(f"{BASE_URL}/agents/{agent_id}", headers=headers)
        if cleanup_resp.status_code == 200:
            print("Agent deleted successfully.")
        else:
            print(f"Failed to delete agent resource: {cleanup_resp.text}")

if __name__ == "__main__":
    main()
