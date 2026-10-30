"""Render recent public GitHub activity as agent tool calls into README.md.

Runs in the profile repo's GitHub Action; stdlib only. Locally:
    GH_USER=Lokesh7025 python scripts/tool_calls.py
"""

import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

USER = os.environ.get("GH_USER", "Lokesh7025")
README = Path(__file__).resolve().parent.parent / "README.md"
START, END = "<!-- tool-calls:start -->", "<!-- tool-calls:end -->"
MAX_LINES = 7


def api(path):
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER},
    )
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def pr_title(repo, number, _cache={}):
    # The events API trims pull_request down to ids, so look the title up.
    if (repo, number) not in _cache:
        try:
            _cache[repo, number] = api(f"repos/{repo}/pulls/{number}").get("title")
        except Exception:
            _cache[repo, number] = None
    return _cache[repo, number]


def clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe(ev):
    """Return (call, detail) for an event, or None to skip it."""
    p, full = ev.get("payload", {}), ev["repo"]["name"]
    repo, kind = full.split("/")[-1], ev["type"]
    if kind == "PushEvent":
        branch = p.get("ref", "").removeprefix("refs/heads/")
        return f"git push origin {clip(branch, 26)}", repo
    if kind == "PullRequestEvent":
        pr = p.get("pull_request", {})
        action = "merge" if p.get("action") == "closed" and pr.get("merged") else p.get("action", "")
        verb = {"opened": "create", "merge": "merge", "closed": "close", "reopened": "reopen"}.get(action)
        if not verb:
            return None
        number = pr.get("number", p.get("number"))
        title = pr.get("title") or (number and pr_title(full, number))
        return f"gh pr {verb}" + (f' "{clip(title, 26)}"' if title else ""), f"{repo}#{number}"
    if kind == "PullRequestReviewEvent":
        state = p.get("review", {}).get("state", "commented").lower()
        return f"gh pr review --{'approve' if state == 'approved' else 'comment'}", f"{repo}#{p.get('pull_request', {}).get('number', '?')}"
    if kind == "IssuesEvent" and p.get("action") in ("opened", "closed"):
        verb = "create" if p["action"] == "opened" else "close"
        return f'gh issue {verb} "{clip(p["issue"].get("title"), 24)}"', f"{repo}#{p['issue']['number']}"
    if kind == "IssueCommentEvent":
        return "gh issue comment", f"{repo}#{p.get('issue', {}).get('number', '?')}"
    if kind == "CreateEvent":
        if p.get("ref_type") == "repository":
            return "Write(new repo)", repo
        if p.get("ref_type") == "branch":
            return f"git switch -c {clip(p.get('ref'), 26)}", repo
        return None
    if kind == "ReleaseEvent":
        return f"Release({p.get('release', {}).get('tag_name', '?')})", repo
    if kind == "WatchEvent":
        return "WebFetch(★ star)", repo
    if kind == "ForkEvent":
        return "Fork()", repo
    return None


def render(events):
    rows = []
    for ev in events:
        if not (d := describe(ev)):
            continue
        when = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00")).strftime("%b %d")
        row = (d[0], d[1], when)
        # Collapse repeated identical calls (five pushes to one branch read as one line).
        if rows and rows[-1][0][:2] == row[:2]:
            rows[-1][1] += 1
            continue
        rows.append([row, 1])
        if len(rows) == MAX_LINES:
            break
    if not rows:
        return "        ● idle, waiting for the next prompt"
    width = max(len(r[0][0]) for r in rows) + 2
    lines = []
    for (call, target, when), n in rows:
        times = f" ×{n}" if n > 1 else ""
        lines.append(f"{when}  ● {call.ljust(width)}{target}{times}")
    return "\n".join(lines)


def main():
    block = f"{START}\n```text\n{render(api(f"users/{USER}/events/public?per_page=60"))}\n```\n{END}"
    text = README.read_text(encoding="utf-8")
    new = re.sub(re.escape(START) + ".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    if new != text:
        README.write_text(new, encoding="utf-8")
        print("README updated")
    else:
        print("no change")


if __name__ == "__main__":
    main()
