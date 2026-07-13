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
"""Seed the Atlassian Chat Agent demo knowledge base.

Uploads the curated Kubernetes troubleshooting docs in `docs/` to a Confluence
space (as a parent page + child pages) so the agent has a realistic knowledge
base to search. Optionally creates a couple of unrelated baseline Jira bugs so
searches return a non-empty backlog.

This uses the Atlassian REST APIs directly (Basic auth with a scoped API token),
routed through `https://api.atlassian.com/ex/{product}/{cloudId}` — the required
base URL for scoped tokens. It is idempotent (pages are matched by title and
updated in place) and everything it creates is labeled `demo-k8s-kb` for easy
cleanup with `--reset`.

Credentials come from the environment (same as chat.py):
  ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN
Site / cloud id (either is enough; cloud id is derived from the site if unset):
  ATLASSIAN_SITE   e.g. https://your-site.atlassian.net
  ATLASSIAN_CLOUD_ID

Usage:
  python3 seed_demo.py                 # upload docs to the SD space
  python3 seed_demo.py --seed-bugs     # also create baseline unrelated bugs
  python3 seed_demo.py --list          # show what is currently seeded
  python3 seed_demo.py --reset         # delete everything labeled demo-k8s-kb
"""

from __future__ import annotations

import argparse
import base64
import html
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(SCRIPT_DIR, "docs")

LABEL = "demo-k8s-kb"
PARENT_TITLE = "SRE Runbooks: Kubernetes Pod Troubleshooting"
DOC_FILES = [
    "01-debug-pods.md",
    "02-determine-reason-pod-failure.md",
    "03-debug-running-pod.md",
]

# Baseline, intentionally UNRELATED bugs (so a search for the demo incident finds
# a non-empty backlog but no matching ticket).
BASELINE_BUGS = [
    {
        "summary": "Login page shows stale avatar after profile update",
        "description": "Users report their profile avatar does not refresh until "
        "a hard reload. Suspected browser cache-control header issue on the "
        "avatar CDN response.",
    },
    {
        "summary": "Nightly analytics export occasionally times out",
        "description": "The 02:00 UTC analytics export job intermittently exceeds "
        "its 15-minute deadline when the events table is large. Needs pagination "
        "or a longer timeout.",
    },
]


# ---------------------------------------------------------------------------
# ANSI helpers.
# ---------------------------------------------------------------------------
class C:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"; CYAN = "\033[36m"


def _c(t: str, c: str) -> str:
    return t if not sys.stdout.isatty() else f"{c}{t}{C.RESET}"


def info(m): print(_c(m, C.CYAN))
def ok(m): print(_c("\u2713 " + m, C.GREEN))
def warn(m): print(_c("! " + m, C.YELLOW))
def err(m): print(_c("\u2717 " + m, C.RED))


# ---------------------------------------------------------------------------
# Auth / config.
# ---------------------------------------------------------------------------
def basic_auth() -> str:
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not email or not token:
        raise SystemExit(
            "Set ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN (source your .env first)."
        )
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def resolve_cloud_id(args: argparse.Namespace) -> str:
    cid = args.cloud_id or os.environ.get("ATLASSIAN_CLOUD_ID")
    if cid:
        return cid
    site = args.site or os.environ.get("ATLASSIAN_SITE")
    if not site:
        raise SystemExit(
            "Provide --cloud-id / ATLASSIAN_CLOUD_ID, or --site / ATLASSIAN_SITE "
            "(e.g. https://your-site.atlassian.net) so the cloud id can be derived."
        )
    site = site.rstrip("/")
    r = requests.get(f"{site}/_edge/tenant_info", timeout=30)
    r.raise_for_status()
    cid = r.json()["cloudId"]
    info(f"Resolved cloudId {cid} from {site}")
    return cid


# ---------------------------------------------------------------------------
# Tiny Markdown -> Confluence storage (XHTML) converter.
#
# Supports the subset used by the curated docs: h2/h3/h4, paragraphs, unordered
# and ordered lists, fenced code blocks, inline bold / code / links.
# ---------------------------------------------------------------------------
_LANG = {"shell": "bash", "sh": "bash", "bash": "bash", "yaml": "yaml",
         "yml": "yaml", "json": "json", "": "none", "none": "none"}


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    return text


def _code_macro(lang: str, body: str) -> str:
    body = body.replace("]]>", "]]]]><![CDATA[>")
    language = _LANG.get(lang.strip().lower(), "none")
    return (
        '<ac:structured-macro ac:name="code" ac:schema-version="1">'
        f'<ac:parameter ac:name="language">{language}</ac:parameter>'
        f"<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def md_to_storage(md: str) -> str:
    out: List[str] = []
    para: List[str] = []
    list_items: List[str] = []
    list_tag: Optional[str] = None
    in_code = False
    code_lang = ""
    code_buf: List[str] = []

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para = []

    def flush_list():
        nonlocal list_items, list_tag
        if list_items and list_tag:
            lis = "".join(f"<li>{_inline(it)}</li>" for it in list_items)
            out.append(f"<{list_tag}>{lis}</{list_tag}>")
        list_items = []
        list_tag = None

    for line in md.splitlines():
        if line.strip().startswith("```"):
            if not in_code:
                flush_para(); flush_list()
                in_code = True
                code_lang = line.strip()[3:]
                code_buf = []
            else:
                out.append(_code_macro(code_lang, "\n".join(code_buf)))
                in_code = False
            continue
        if in_code:
            code_buf.append(line)
            continue

        if not line.strip():
            flush_para(); flush_list()
            continue

        m = re.match(r"^(#{2,4})\s+(.*)$", line)
        if m:
            flush_para(); flush_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            continue

        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            flush_para()
            if list_tag not in (None, "ul"):
                flush_list()
            list_tag = "ul"
            list_items.append(m.group(1).strip())
            continue

        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            flush_para()
            if list_tag not in (None, "ol"):
                flush_list()
            list_tag = "ol"
            list_items.append(m.group(1).strip())
            continue

        para.append(line.strip())

    if in_code:  # unterminated fence (shouldn't happen)
        out.append(_code_macro(code_lang, "\n".join(code_buf)))
    flush_para(); flush_list()
    return "".join(out)


def parse_doc(path: str) -> Tuple[str, str, str]:
    """Return (title, source_url, storage_body) for a curated doc file."""
    with open(path, "r") as f:
        raw = f.read()
    title = source = ""
    body = raw
    if raw.startswith("title:"):
        head, _, body = raw.partition("\n---\n")
        for ln in head.splitlines():
            if ln.startswith("title:"):
                title = ln.split(":", 1)[1].strip()
            elif ln.startswith("source:"):
                source = ln.split(":", 1)[1].strip()
    attribution = (
        '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>'
        f'Imported from <a href="{html.escape(source)}">kubernetes.io</a> '
        "\u2014 \u00a9 The Kubernetes Authors, licensed under "
        '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. '
        "Seeded for the Atlassian Chat Agent demo knowledge base."
        "</p></ac:rich-text-body></ac:structured-macro>"
    )
    return title, source, attribution + md_to_storage(body)


# ---------------------------------------------------------------------------
# Atlassian REST client.
# ---------------------------------------------------------------------------
class Atlassian:
    def __init__(self, cloud_id: str, auth: str):
        self.c = f"https://api.atlassian.com/ex/confluence/{cloud_id}"
        self.j = f"https://api.atlassian.com/ex/jira/{cloud_id}"
        self.h = {"Authorization": auth, "Accept": "application/json"}
        self.hj = {**self.h, "Content-Type": "application/json"}

    def _check(self, r: requests.Response, what: str) -> requests.Response:
        if r.status_code >= 400:
            raise RuntimeError(f"{what} -> HTTP {r.status_code}: {r.text[:400]}")
        return r

    # --- Confluence ---
    def space_id(self, key: str) -> str:
        r = self._check(
            requests.get(f"{self.c}/wiki/api/v2/spaces", headers=self.h,
                         params={"keys": key, "limit": 1}, timeout=30),
            f"get space {key}")
        results = r.json().get("results", [])
        if not results:
            raise SystemExit(f"Confluence space '{key}' not found.")
        return results[0]["id"]

    def find_page(self, space_id: str, title: str) -> Optional[Dict[str, Any]]:
        r = self._check(
            requests.get(f"{self.c}/wiki/api/v2/pages", headers=self.h,
                         params={"space-id": space_id, "title": title,
                                 "limit": 1}, timeout=30),
            f"find page {title!r}")
        results = r.json().get("results", [])
        return results[0] if results else None

    def upsert_page(self, space_id: str, title: str, body: str,
                    parent_id: Optional[str]) -> str:
        existing = self.find_page(space_id, title)
        if existing:
            pid = existing["id"]
            cur = self._check(
                requests.get(f"{self.c}/wiki/api/v2/pages/{pid}", headers=self.h,
                             params={"body-format": "storage"}, timeout=30),
                "get page version")
            ver = cur.json()["version"]["number"]
            payload = {"id": pid, "status": "current", "title": title,
                       "body": {"representation": "storage", "value": body},
                       "version": {"number": ver + 1, "message": "demo seed update"}}
            self._check(requests.put(f"{self.c}/wiki/api/v2/pages/{pid}",
                                     headers=self.hj, json=payload, timeout=60),
                        "update page")
            action = "updated"
        else:
            payload = {"spaceId": space_id, "status": "current", "title": title,
                       "body": {"representation": "storage", "value": body}}
            if parent_id:
                payload["parentId"] = parent_id
            r = self._check(requests.post(f"{self.c}/wiki/api/v2/pages",
                                          headers=self.hj, json=payload, timeout=60),
                            "create page")
            pid = r.json()["id"]
            action = "created"
        ok(f"{action} page: {title}  (id={pid})")
        return pid

    def find_seeded_pages(self, space_id: str, titles: List[str]) -> List[Dict[str, str]]:
        """Find seeded pages by their known titles.

        Confluence page labels can't be written with a scoped API token (the v1
        label endpoint requires a scope the token doesn't carry, and v2 has no
        label-create endpoint), so we track seeded pages by title instead.
        """
        found = []
        for title in titles:
            page = self.find_page(space_id, title)
            if page:
                found.append({"id": page["id"], "title": title})
        return found

    def delete_page(self, page_id: str) -> None:
        requests.delete(f"{self.c}/wiki/api/v2/pages/{page_id}",
                        headers=self.h, timeout=30)

    # --- Jira ---
    def create_bug(self, project: str, summary: str, description: str) -> str:
        adf = {"type": "doc", "version": 1, "content": [
            {"type": "paragraph",
             "content": [{"type": "text", "text": description}]}]}
        payload = {"fields": {
            "project": {"key": project},
            "summary": summary,
            "issuetype": {"name": "Bug"},
            "labels": [LABEL],
            "description": adf,
        }}
        r = self._check(requests.post(f"{self.j}/rest/api/3/issue",
                                      headers=self.hj, json=payload, timeout=60),
                        "create bug")
        key = r.json()["key"]
        ok(f"created bug: {key}  {summary}")
        return key

    def find_labeled_issues(self, project: str) -> List[Dict[str, str]]:
        r = self._check(
            requests.get(f"{self.j}/rest/api/3/search/jql", headers=self.h,
                         params={"jql": f'project="{project}" AND labels="{LABEL}"',
                                 "fields": "summary", "maxResults": 100}, timeout=30),
            "search labeled issues")
        return [{"key": i["key"], "summary": i["fields"].get("summary", "?")}
                for i in r.json().get("issues", [])]

    def delete_issue(self, key: str) -> None:
        requests.delete(f"{self.j}/rest/api/3/issue/{key}",
                        headers=self.h, timeout=30)


# ---------------------------------------------------------------------------
# Actions.
# ---------------------------------------------------------------------------
def do_seed(at: Atlassian, space_key: str, project: str, seed_bugs: bool) -> None:
    space_id = at.space_id(space_key)
    info(f"Confluence space '{space_key}' -> id {space_id}")

    parent_body = md_to_storage(
        "This runbook collection helps on-call engineers triage misbehaving "
        "Kubernetes **Pods** (crash loops, image pull failures, pending/"
        "unschedulable Pods, and container exit reasons).\n\n"
        "The pages below are imported from the official Kubernetes documentation "
        "(CC BY 4.0) for the Atlassian Chat Agent demo."
    )
    parent_id = at.upsert_page(space_id, PARENT_TITLE, parent_body, None)

    for fname in DOC_FILES:
        title, _src, body = parse_doc(os.path.join(DOCS_DIR, fname))
        at.upsert_page(space_id, title, body, parent_id)

    if seed_bugs:
        existing = {b["summary"] for b in at.find_labeled_issues(project)}
        for bug in BASELINE_BUGS:
            if bug["summary"] in existing:
                info(f"baseline bug already exists: {bug['summary']}")
                continue
            at.create_bug(project, bug["summary"], bug["description"])

    print()
    ok("Seed complete.")
    info(f"Confluence: parent '{PARENT_TITLE}' + {len(DOC_FILES)} child pages in "
         f"space '{space_key}'.")
    if seed_bugs:
        info(f"Jira: baseline bugs created in '{project}'.")


def seeded_titles() -> List[str]:
    """The titles this seeder creates (parent + one per curated doc)."""
    titles = [PARENT_TITLE]
    for fname in DOC_FILES:
        title, _src, _body = parse_doc(os.path.join(DOCS_DIR, fname))
        titles.append(title)
    return titles


def do_list(at: Atlassian, space_key: str, project: str) -> None:
    space_id = at.space_id(space_key)
    info(f"Seeded Confluence pages in space '{space_key}':")
    for p in at.find_seeded_pages(space_id, seeded_titles()):
        print(f"  - {p['title']}  (id={p['id']})")
    info(f"Jira issues in {project} labeled {LABEL}:")
    for i in at.find_labeled_issues(project):
        print(f"  - {i['key']}  {i['summary']}")


def do_reset(at: Atlassian, space_key: str, project: str) -> None:
    space_id = at.space_id(space_key)
    # Delete child docs before the parent to avoid re-parenting surprises.
    pages = at.find_seeded_pages(space_id, seeded_titles())
    pages.sort(key=lambda p: p["title"] == PARENT_TITLE)  # parent last
    for p in pages:
        at.delete_page(p["id"])
        warn(f"deleted page: {p['title']} (id={p['id']})")
    issues = at.find_labeled_issues(project)
    for i in issues:
        at.delete_issue(i["key"])
        warn(f"deleted issue: {i['key']} {i['summary']}")
    ok(f"Reset complete. Removed {len(pages)} page(s) and {len(issues)} issue(s).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed the Atlassian Chat Agent demo.")
    ap.add_argument("--space", default="SD", help="Confluence space key (default SD).")
    ap.add_argument("--project", default="SCRUM", help="Jira project key (default SCRUM).")
    ap.add_argument("--site", help="Atlassian site URL (else ATLASSIAN_SITE).")
    ap.add_argument("--cloud-id", help="Atlassian cloud id (else ATLASSIAN_CLOUD_ID / derived).")
    ap.add_argument("--seed-bugs", action="store_true",
                    help="Also create baseline (unrelated) Jira bugs.")
    ap.add_argument("--list", action="store_true", help="List seeded content and exit.")
    ap.add_argument("--reset", action="store_true",
                    help="Delete everything labeled " + LABEL + " and exit.")
    args = ap.parse_args()

    auth = basic_auth()
    cloud_id = resolve_cloud_id(args)
    at = Atlassian(cloud_id, auth)

    try:
        if args.reset:
            do_reset(at, args.space, args.project)
        elif args.list:
            do_list(at, args.space, args.project)
        else:
            do_seed(at, args.space, args.project, args.seed_bugs)
    except (RuntimeError, requests.RequestException) as e:
        err(str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
