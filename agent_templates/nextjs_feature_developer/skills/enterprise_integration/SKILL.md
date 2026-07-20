---
name: Enterprise Integration Skill
description: Guides the agent on how to interact with Jira for ticket management and Confluence for documentation writing using Python.
---

# Enterprise Integration Skill: Jira & Confluence Automation

You are tasked with automating the Software Development Lifecycle by interacting directly with enterprise tools like Jira and Confluence. This skill provides the standard operating procedures for fetching ticket requirements and publishing technical documentation.

### Authenticating with Enterprise Services

You should use the `atlassian-python-api` library to interact with Jira and Confluence. 
If the library is not installed in your sandbox environment, you must install it dynamically at the start of your execution:

```python
import subprocess
import sys

# Ensure required libraries are installed
subprocess.check_call([sys.executable, "-m", "pip", "install", "atlassian-python-api"])
```

### Fetching Requirements from Jira

When a user provides a Jira Ticket ID (e.g., `PROJ-123`), use the API to fetch its description, comments, and acceptance criteria.

```python
import os
from atlassian import Jira

# Read credentials injected from the environment
JIRA_URL = os.environ.get("JIRA_URL", "https://your-domain.atlassian.net")
JIRA_USER = os.environ.get("JIRA_USER", "agent@company.com")
JIRA_TOKEN = os.environ.get("JIRA_API_TOKEN", "mock_token")

jira = Jira(
    url=JIRA_URL,
    username=JIRA_USER,
    password=JIRA_TOKEN,
    cloud=True
)

def fetch_ticket_details(ticket_id):
    try:
        # Fetch the issue
        issue = jira.issue(ticket_id)
        summary = issue['fields']['summary']
        description = issue['fields']['description']
        
        print(f"--- Ticket {ticket_id}: {summary} ---")
        print(f"Description:\n{description}")
        return issue
    except Exception as e:
        print(f"Mock fallback: Could not reach Jira for {ticket_id}. Simulating ticket data...")
        return {
            "summary": "Implement user authentication login flow",
            "description": "Create a secure login page using JWT tokens. Acceptance Criteria: 1. Username/password fields 2. Error handling 3. Redirect to dashboard."
        }

# Example usage
ticket_data = fetch_ticket_details("PROJ-123")
```

### Publishing Design Docs to Confluence

After writing your code or technical design, you must publish a summary back to Confluence so the rest of the team can review it.

```python
from atlassian import Confluence

CONFLUENCE_URL = os.environ.get("CONFLUENCE_URL", "https://your-domain.atlassian.net")

confluence = Confluence(
    url=CONFLUENCE_URL,
    username=JIRA_USER,
    password=JIRA_TOKEN,
    cloud=True
)

def publish_documentation(space, title, body_html):
    try:
        status = confluence.create_page(
            space=space,
            title=title,
            body=body_html
        )
        print(f"Successfully published Confluence page: {title}")
    except Exception as e:
        print(f"Mock fallback: Confluence API unavailable. Generating local markdown file instead.")
        with open("confluence_draft.md", "w") as f:
            f.write(f"# {title}\n\n{body_html}")

# Example usage
html_content = "<h2>Implementation Plan</h2><p>The login flow will be implemented using Next.js and standard JWT tokens...</p>"
publish_documentation("ENG", "Tech Spec: PROJ-123 Login Flow", html_content)
```

### Critical Rules
1. **Always Fallback to Mocks for Testing**: The user might run this agent without real Jira/Confluence credentials. Always wrap your API calls in `try/except` blocks and provide simulated mock data so the agent can still demonstrate its coding and document generation capabilities!
2. **Be Comprehensive**: The design document you publish to Confluence should be detailed, containing Architecture Diagrams (using Mermaid), code snippets, and security considerations.
