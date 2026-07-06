# GitHub Automation Skill: Repository & File Operations

You have access to a custom Python helper module located in your workspace at `/.agents/skills/github_automation/github_helper.py`.

This module (`github_helper.py`) exposes the `GitHubHelper` class, which allows you to perform git operations (reading files, listing directories, creating branches, committing changes, and opening PRs) directly via GitHub's REST API without requiring a local git installation.

### How to use the helper:

1.  Write a Python script that imports the helper class.
2.  You **must** add the skill directory to your Python path before importing:
    ```python
    import sys
    sys.path.append('/.agents/skills/github_automation')
    from github_helper import GitHubHelper
    ```
3.  Initialize the helper. You will be provided with the repository owner, and repository name in your prompt. The token will be read from the GITHUB_TOKEN environment variable.
    ```python
    # Initialize the helper
    gh = GitHubHelper(repo_owner="OWNER", repo_name="REPO")
    ```
4.  Use the helper's methods to carry out the automated changes:
    *   `gh.list_directory(path)`: List contents of a directory.
    *   `gh.get_file_contents(path)`: Read an existing file's text.
    *   `gh.create_branch(branch_name)`: Create a branch (e.g., `feature/awesome-addition`) to store your edits.
    *   `gh.create_or_update_file(path, content, commit_message, branch_name)`: Commit a file to the branch.
    *   `gh.create_pull_request(title, body, head_branch)`: Create a PR back to `main`.

### Safety Guidelines & Constraints:
*   **DO NOT merge the Pull Request yourself**. You are strictly limited to creating the branch, committing files, and opening the Pull Request. The Pull Request must be reviewed and merged by a human.
*   Do not attempt to write scripts that call the GitHub merge API endpoints.

---

### Example Python Script to Run in Sandbox:

```python
import sys
sys.path.append('/.agents/skills/github_automation')
from github_helper import GitHubHelper

# 1. Initialize
gh = GitHubHelper(repo_owner="fuzerg", repo_name="Slow-Code-Example")

# 2. Create target branch
branch_name = "feature/new-example-addition"
gh.create_branch(branch_name)

# 3. Create or update files on that branch
new_code = "print('Hello from the automated code example!')"
gh.create_or_update_file(
    path="showcase/new_example/main.py",
    content=new_code,
    commit_message="Add automated hello-world script",
    branch_name=branch_name
)

# 4. Open a Pull Request
pr_url = gh.create_pull_request(
    title="Add Automated Hello World Example",
    body="This PR was automatically created by the Gemini Interactions API agent using the Cloud Sandbox + GitHub API Route.",
    head_branch=branch_name
)

# 5. Output the PR link so the caller script can print it
print(f"__PR_URL_START__{pr_url}__PR_URL_END__")
```

Always follow this pattern to write files, create branches, and open pull requests. Wrap the final Pull Request URL in `__PR_URL_START__` and `__PR_URL_END__` markers in your stdout so the client runner script can extract and present it to the user.
