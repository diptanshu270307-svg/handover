from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import httpx

from app.config import settings
from app.models import SourceType


@dataclass
class NormalizedGitHubDoc:
    source_type: SourceType
    title: str
    uri: str
    version_sha: str | None
    source_date: datetime | None
    content: str
    filename: str


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_repo_slug(repo: str) -> str:
    repo = repo.strip().rstrip("/")
    match = re.match(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?$", repo)
    if match:
        return match.group(1)
    if "/" in repo and len(repo.split("/")) == 2:
        return repo
    raise ValueError(f"Invalid GitHub repository identifier: {repo}")


def _normalize_fixture_payload(data: dict) -> list[NormalizedGitHubDoc]:
    commit_sha = data.get("commit_sha")
    docs: list[NormalizedGitHubDoc] = []

    for f in data.get("files", []):
        docs.append(
            NormalizedGitHubDoc(
                source_type=SourceType.github_file,
                title=f["path"],
                uri=f["permalink"],
                version_sha=commit_sha,
                source_date=_parse_iso(f.get("updated_at")),
                content=f["content"],
                filename=f["path"].replace("/", "_"),
            )
        )

    for issue in data.get("issues", []):
        comments_txt = "\n\n".join(
            f"Comment by @{c.get('author', 'unknown')} ({c.get('created_at', '')}):\n{c.get('body', '')}"
            for c in issue.get("comments", [])
        )
        body = (
            f"Issue #{issue['number']}: {issue['title']}\n"
            f"State: {issue.get('state', 'open')} | Author: @{issue.get('author', 'unknown')}\n"
            f"Permalink: {issue['permalink']}\n\n"
            f"{issue.get('body', '')}"
        )
        if comments_txt:
            body += f"\n\n## Discussion\n{comments_txt}"
        docs.append(
            NormalizedGitHubDoc(
                source_type=SourceType.github_issue,
                title=f"Issue #{issue['number']}: {issue['title']}",
                uri=issue["permalink"],
                version_sha=commit_sha,
                source_date=_parse_iso(issue.get("updated_at") or issue.get("created_at")),
                content=body,
                filename=f"issue_{issue['number']}.md",
            )
        )

    for pr in data.get("pull_requests", []):
        comments_txt = "\n\n".join(
            f"PR Discussion by @{c.get('author', 'unknown')} ({c.get('created_at', '')}):\n{c.get('body', '')}"
            for c in pr.get("comments", [])
        )
        body = (
            f"PR #{pr['number']}: {pr['title']}\n"
            f"State: {pr.get('state', 'open')} (draft={pr.get('draft', False)}) | "
            f"Author: @{pr.get('author', 'unknown')}\n"
            f"Head SHA: {pr.get('head_sha') or commit_sha}\n"
            f"Permalink: {pr['permalink']}\n\n"
            f"{pr.get('body', '')}"
        )
        if comments_txt:
            body += f"\n\n## PR Discussion\n{comments_txt}"
        docs.append(
            NormalizedGitHubDoc(
                source_type=SourceType.github_pr,
                title=f"PR #{pr['number']}: {pr['title']}",
                uri=pr["permalink"],
                version_sha=pr.get("head_sha") or commit_sha,
                source_date=_parse_iso(pr.get("updated_at") or pr.get("created_at")),
                content=body,
                filename=f"pr_{pr['number']}.md",
            )
        )

    return docs


def fetch_github_sources(
    repo: str,
    use_fixture: bool = True,
    fixture_path: str | None = None,
) -> list[NormalizedGitHubDoc]:
    if use_fixture:
        path = Path(fixture_path or settings.github_fixture_path)
        if not path.exists():
            raise FileNotFoundError(f"GitHub fixture not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_fixture_payload(data)

    slug = _parse_repo_slug(repo)
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    docs: list[NormalizedGitHubDoc] = []
    with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=15.0) as client:
        repo_resp = client.get(f"/repos/{slug}")
        repo_resp.raise_for_status()
        default_branch = repo_resp.json().get("default_branch", "main")

        branch_resp = client.get(f"/repos/{slug}/branches/{default_branch}")
        branch_resp.raise_for_status()
        commit_sha = branch_resp.json()["commit"]["sha"]
        commit_date = _parse_iso(branch_resp.json()["commit"]["commit"]["committer"].get("date"))

        # Pull README + docs/*.md
        tree_resp = client.get(f"/repos/{slug}/git/trees/{commit_sha}?recursive=1")
        tree_resp.raise_for_status()
        target_paths = [
            item["path"]
            for item in tree_resp.json().get("tree", [])
            if item.get("type") == "blob"
            and (item["path"].lower() == "readme.md" or item["path"].lower().startswith("docs/"))
            and item["path"].lower().endswith((".md", ".txt"))
        ][:10]

        for path in target_paths:
            raw_resp = client.get(
                f"/repos/{slug}/contents/{path}",
                params={"ref": commit_sha},
                headers={**headers, "Accept": "application/vnd.github.raw+json"},
            )
            if raw_resp.status_code == 200:
                docs.append(
                    NormalizedGitHubDoc(
                        source_type=SourceType.github_file,
                        title=path,
                        uri=f"https://github.com/{slug}/blob/{commit_sha}/{path}",
                        version_sha=commit_sha,
                        source_date=commit_date or datetime.now(timezone.utc),
                        content=raw_resp.text,
                        filename=path.replace("/", "_"),
                    )
                )

        # Pull Issues (excluding PRs) & PRs with discussion comments
        issues_resp = client.get(
            f"/repos/{slug}/issues",
            params={"state": "all", "per_page": 15, "sort": "updated", "direction": "desc"},
        )
        issues_resp.raise_for_status()
        for item in issues_resp.json():
            number = item["number"]
            is_pr = "pull_request" in item
            comments_resp = client.get(f"/repos/{slug}/issues/{number}/comments", params={"per_page": 20})
            comments = comments_resp.json() if comments_resp.status_code == 200 else []
            comments_txt = "\n\n".join(
                f"Comment by @{c.get('user', {}).get('login', 'unknown')} ({c.get('created_at', '')}):\n{c.get('body', '')}"
                for c in comments
            )

            head_sha = commit_sha
            if is_pr:
                pr_resp = client.get(f"/repos/{slug}/pulls/{number}")
                if pr_resp.status_code == 200:
                    head_sha = pr_resp.json().get("head", {}).get("sha") or commit_sha

            body = (
                f"{'PR' if is_pr else 'Issue'} #{number}: {item['title']}\n"
                f"State: {item.get('state')} | Author: @{item.get('user', {}).get('login', 'unknown')}\n"
                f"Permalink: {item['html_url']}\n\n"
                f"{item.get('body') or ''}"
            )
            if comments_txt:
                body += f"\n\n## Discussion\n{comments_txt}"

            docs.append(
                NormalizedGitHubDoc(
                    source_type=SourceType.github_pr if is_pr else SourceType.github_issue,
                    title=f"{'PR' if is_pr else 'Issue'} #{number}: {item['title']}",
                    uri=item["html_url"],
                    version_sha=head_sha,
                    source_date=_parse_iso(item.get("updated_at") or item.get("created_at")),
                    content=body,
                    filename=f"{'pr' if is_pr else 'issue'}_{number}.md",
                )
            )

    return docs
