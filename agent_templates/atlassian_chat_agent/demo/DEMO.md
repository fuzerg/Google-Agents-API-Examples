# Demo: Kubernetes incident triage with Jira + Confluence

This demo turns the Atlassian Chat Agent into a realistic **on-call triage
assistant**. It seeds a Confluence knowledge base with official Kubernetes
troubleshooting runbooks, then walks two connected use cases:

1. **Report → research → file.** A user reports a crashing pod. The agent
   searches Confluence + Jira, finds general runbooks but **no existing ticket
   or resolution**, and (on request) files a Jira bug capturing the context.
2. **Similar report → find existing.** A second user reports the same symptom.
   The agent searches Jira, **finds the ticket from use case 1**, and returns
   its status and captured context.

It also shows the agent answering questions the docs **can** cover and honestly
declining ones they **cannot** — i.e. grounding, not hallucination.

---

## What gets seeded

**Confluence** (space `SD` — "Software Development"): a parent page
**"SRE Runbooks: Kubernetes Pod Troubleshooting"** with three child pages
imported from the official Kubernetes documentation:

| Page | Source (kubernetes.io) |
| --- | --- |
| Debug Pods | `/docs/tasks/debug/debug-application/debug-pods/` |
| Determine the Reason for Pod Failure | `/docs/tasks/debug/debug-application/determine-reason-pod-failure/` |
| Debug Running Pods | `/docs/tasks/debug/debug-application/debug-running-pod/` |

> The runbook content is © The Kubernetes Authors, licensed under
> [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Each seeded page
> carries an attribution panel linking back to its source. The local copies live
> in [`docs/`](docs/).

**Jira** (project `SCRUM`, with `--seed-bugs`): two intentionally *unrelated*
baseline bugs, so a search returns a non-empty backlog with **no** matching
ticket for the demo incident.

Cleanup: the seeded Confluence pages are tracked by their (known) titles, and the
seeded Jira bugs are labeled `demo-k8s-kb`. `--reset` removes both. (Confluence
page labels can't be set with a scoped API token, so the seeder identifies its
pages by title instead.)

---

## Setup

From the template directory (`agent_templates/atlassian_chat_agent`):

1. **Prerequisites** (see [../README.md](../README.md)): a **scoped** Atlassian
   API token with API-token auth enabled for the Rovo MCP server, and ADC for
   the Interactions API.
2. **Credentials** in `.env` (git-ignored) — the seeder also needs your site:
   ```bash
   ATLASSIAN_EMAIL="you@example.com"
   ATLASSIAN_API_TOKEN="<scoped token>"
   ATLASSIAN_SITE="https://your-site.atlassian.net"
   ```
3. **Seed** the knowledge base and baseline bugs:
   ```bash
   set -a && source .env && set +a
   ../../venv/bin/python3 demo/seed_demo.py --seed-bugs
   ```
   `seed_demo.py` is idempotent (pages are matched by title and updated in place).
   Use `--list` to see seeded content and `--reset` to remove it.

> **Note on scoped tokens:** the seeder talks to the REST API through
> `https://api.atlassian.com/ex/{product}/{cloudId}` (required for scoped
> tokens); it derives the cloud id from `ATLASSIAN_SITE`.

---

## Use case 1 — report → research → file a ticket (multi-turn)

Run an interactive session and send these turns:

```bash
set -a && source .env && set +a
../../venv/bin/python3 chat.py --project YOUR_GCP_PROJECT --interactive
```

**Turn 1 (User A reports):**
> Our checkout-service pod keeps crashing and restarting in staging — kubectl
> shows CrashLoopBackOff. Search our internal Confluence runbooks AND existing
> Jira bug tickets for anything relevant, then summarize what you found and
> whether there is a documented resolution.

*Expected:* the agent calls `getAccessibleAtlassianResources` (cloudId), searches
Jira (`searchJiraIssuesUsingJql`) and Confluence (`searchConfluenceUsingCql`),
reports **no matching ticket**, surfaces the three runbooks, and extracts the
concrete debugging steps (`kubectl logs --previous`, `kubectl describe pod`,
exit codes / termination message) — noting there is no service-specific
resolution.

**Turn 2 (User A asks to file):**
> There is no existing ticket. You are pre-authorized to create exactly ONE Bug
> in the SCRUM project now — do not ask me to confirm. In the description include
> the symptom, the concrete debugging steps from the runbooks (with the kubectl
> commands), and links to the Confluence pages you used. Reply with the new
> issue key.

*Expected:* the agent calls `createJiraIssue` and returns the new key (e.g.
`SCRUM-3`). The description contains the symptom, the runbook-derived kubectl
steps, and links to the Confluence pages.

> **Why "pre-authorized"?** `AGENTS.md` tells the agent to **confirm before
> mutating**. In a live chat it will ask "shall I create it?" first — good
> behavior. For a scripted/non-interactive run, the explicit pre-authorization
> lets it create the ticket in one turn instead of waiting for a confirmation.

---

## Use case 2 — similar report → find the existing ticket (new conversation)

Start a **fresh** run (no `--interactive` needed) so there is no shared context:

```bash
set -a && source .env && set +a
../../venv/bin/python3 chat.py --project YOUR_GCP_PROJECT \
  "I'm on the payments team. In production our checkout-service pods are going into CrashLoopBackOff after the latest deploy. Is this already being tracked in Jira? If so, give me the ticket key, its status, and a short summary of the context and recommended debugging steps already captured on it."
```

*Expected:* the agent searches Jira, **finds the ticket from use case 1**, and
returns its key, status, and the captured context (symptom + kubectl debugging
steps). This demonstrates deduplication of duplicate incident reports.

---

## Questions the knowledge base CAN answer (grounded)

- "How do I make Kubernetes capture a container's final termination message and
  fall back to container logs on error?" → *Determine the Reason for Pod
  Failure* (`terminationMessagePolicy: FallbackToLogsOnError`).
- "How do I get the crash logs for a container stuck in CrashLoopBackOff?" →
  *Debug Running Pods* (`kubectl logs --previous`).
- "Why would a pod stay `Pending`, and how do I find out?" → *Debug Pods* /
  *Debug Running Pods* (scheduler events, insufficient resources).
- "What causes a pod stuck in `Waiting`?" → *Debug Pods* (image pull failure —
  check image name / registry / manual pull).
- "How can I debug a crashed container that has no shell?" → *Debug Running Pods*
  (ephemeral containers via `kubectl debug`).

## Questions it CANNOT answer (should decline, not invent)

- "How do I configure a Kubernetes NetworkPolicy to restrict a pod's egress
  traffic?" (networking docs were not seeded)
- "How does the Horizontal Pod Autoscaler decide when to scale?" (HPA doc not
  seeded)
- "What is our production cluster's node pool size / cloud provider?"
  (deployment-specific, not in any doc)
- "What's our company's on-call escalation policy?" (internal policy, not seeded)

The agent's `AGENTS.md` instructs it to ground answers in tool results and say so
plainly when nothing matches.

---

## Cleanup

```bash
set -a && source .env && set +a
../../venv/bin/python3 demo/seed_demo.py --reset
```

`--reset` deletes everything the **seeder** created (Confluence pages by title,
baseline Jira bugs by the `demo-k8s-kb` label). The bug the **agent** files in
use case 1 (e.g. `SCRUM-3`) is created by the model and is **not** labeled, so
delete it manually if you want a clean slate:

```bash
# via the agent, or the Jira UI, or the REST API
```
