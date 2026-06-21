"""Public URLs for committed daily output files.

Resolves the GitHub repo/branch from CI env vars, explicit overrides, or
local git metadata so report.json can hand LLMs fetchable raw links.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from config import settings

_GITHUB_REMOTE = re.compile(
    r"(?:github\.com[/:]|git@github\.com:)(?P<repo>[^/]+/[^/.]+)"
)


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=settings.ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _parse_github_remote(url: str) -> str | None:
    url = url.removesuffix(".git")
    match = _GITHUB_REMOTE.search(url)
    return match.group("repo") if match else None


def repo_slug() -> str | None:
    explicit = os.getenv("PARKHU_GITHUB_REPO") or os.getenv("GITHUB_REPOSITORY")
    if explicit:
        return explicit.strip().removesuffix(".git")
    remote = _git("remote", "get-url", "origin")
    return _parse_github_remote(remote) if remote else None


def repo_branch() -> str:
    for key in ("PARKHU_GITHUB_BRANCH", "GITHUB_REF_NAME"):
        if value := os.getenv(key):
            return value.removeprefix("refs/heads/")
    ref = os.getenv("GITHUB_REF")
    if ref:
        return ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
    return _git("branch", "--show-current") or "main"


def output_rel_path(date: str) -> str:
    return f"output/{date}"


def file_rel_path(date: str, filename: str) -> str:
    return f"{output_rel_path(date)}/{filename}"


def download_url(date: str, filename: str) -> str | None:
    """Raw GitHub URL — plain text, suitable for LLM fetch."""
    slug = repo_slug()
    if not slug:
        return None
    return (
        f"https://raw.githubusercontent.com/{slug}/{repo_branch()}/"
        f"{file_rel_path(date, filename)}"
    )


def preview_url(date: str, filename: str) -> str | None:
    """GitHub blob URL — human-readable preview in the browser."""
    slug = repo_slug()
    if not slug:
        return None
    return (
        f"https://github.com/{slug}/blob/{repo_branch()}/"
        f"{file_rel_path(date, filename)}"
    )


def folder_preview_url(date: str) -> str | None:
    slug = repo_slug()
    if not slug:
        return None
    return f"https://github.com/{slug}/tree/{repo_branch()}/{output_rel_path(date)}"


def file_links(date: str, out_dir: Path | None = None) -> dict[str, dict[str, str | None]]:
    """Public links for every file in output/<date>/."""
    out_dir = out_dir or settings.daily_output_dir(date)
    links: dict[str, dict[str, str | None]] = {}
    if not out_dir.is_dir():
        return links
    for path in sorted(out_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        links[name] = {
            "download_url": download_url(date, name),
            "preview_url": preview_url(date, name),
        }
    return links
