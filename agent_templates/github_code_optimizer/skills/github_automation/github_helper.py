import os
import base64
import requests

class GitHubHelper:
    """
    A lightweight wrapper around the GitHub REST API v3 to enable file operations,
    branch management, and pull request creation inside the agent sandbox.
    Supports a mock mode for testing/prober evaluation.
    """
    def __init__(self, repo_owner: str, repo_name: str):
        token = os.environ.get("GITHUB_TOKEN")
        
        # Fallback to reading from .env file in the same directory (mounted via GCS)
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if not token and os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("GITHUB_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
                        
        if not token:
            raise ValueError("GITHUB_TOKEN environment variable or .env file is required.")
        self.token = token
        self.owner = repo_owner
        self.repo = repo_name
        self.base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }

    def get_latest_commit_sha(self, branch: str = "main") -> str:
        """Retrieves the SHA of the latest commit on a branch."""
        url = f"{self.base_url}/git/ref/heads/{branch}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch branch ref '{branch}': {response.text}")
        return response.json()["object"]["sha"]

    def create_branch(self, branch_name: str, parent_branch: str = "main") -> str:
        """Creates a new branch from the parent branch."""
        parent_sha = self.get_latest_commit_sha(parent_branch)
        url = f"{self.base_url}/git/refs"
        payload = {
            "ref": f"refs/heads/{branch_name}",
            "sha": parent_sha
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            print(f"Successfully created branch '{branch_name}' from '{parent_branch}'.")
            return branch_name
        elif response.status_code == 422: # Branch already exists
            print(f"Branch '{branch_name}' already exists.")
            return branch_name
        else:
            raise Exception(f"Failed to create branch: {response.text}")

    def get_file_sha(self, path: str, branch: str) -> str:
        """Helper to get the SHA of a file on a branch, if it exists."""
        url = f"{self.base_url}/contents/{path}"
        params = {"ref": branch}
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code == 200:
            return response.json().get("sha")
        return None

    def create_or_update_file(self, path: str, content: str, commit_message: str, branch_name: str) -> dict:
        """Creates or updates a file on a specific branch."""
        url = f"{self.base_url}/contents/{path}"
        
        # Base64 encode the content
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        
        payload = {
            "message": commit_message,
            "content": encoded_content,
            "branch": branch_name
        }
        
        # Check if file exists to fetch its SHA (required for updates)
        file_sha = self.get_file_sha(path, branch_name)
        if file_sha:
            payload["sha"] = file_sha
            
        response = requests.put(url, headers=self.headers, json=payload)
        if response.status_code in [200, 201]:
            print(f"Successfully committed file '{path}' to branch '{branch_name}'.")
            return response.json()
        else:
            raise Exception(f"Failed to commit file '{path}': {response.text}")

    def get_file_contents(self, path: str, branch_name: str = "main") -> str:
        """Reads file contents from a specific branch."""
        url = f"{self.base_url}/contents/{path}"
        params = {"ref": branch_name}
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"Failed to read file '{path}' from branch '{branch_name}': {response.text}")
        
        file_data = response.json()
        if "content" in file_data:
            # Decode base64 content
            return base64.b64decode(file_data["content"]).decode("utf-8")
        raise Exception(f"Path '{path}' is not a file or has no content.")

    def list_directory(self, path: str = "", branch_name: str = "main") -> list:
        """Lists files and directories under a path."""
        url = f"{self.base_url}/contents/{path}"
        params = {"ref": branch_name}
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"Failed to list path '{path}' on branch '{branch_name}': {response.text}")
        
        contents = response.json()
        if not isinstance(contents, list):
            # It's a file, not a directory
            return [contents]
            
        items = []
        for item in contents:
            items.append({
                "name": item["name"],
                "path": item["path"],
                "type": item["type"], # 'file' or 'dir'
                "size": item.get("size", 0)
            })
        return items

    def create_pull_request(self, title: str, body: str, head_branch: str, base_branch: str = "main") -> str:
        """Creates a Pull Request on GitHub."""
        url = f"{self.base_url}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            pr_url = response.json()["html_url"]
            print(f"Successfully created Pull Request: {pr_url}")
            return pr_url
        else:
            raise Exception(f"Failed to create Pull Request: {response.text}")
