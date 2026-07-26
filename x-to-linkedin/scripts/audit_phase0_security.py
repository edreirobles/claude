"""Audit tracked files and compare active secrets with historical .env files.

The script reports names and counts only. It never prints secret values.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "LINKEDIN_CLIENT_SECRET",
    "LINKEDIN_LI_AT",
    "LINKEDIN_JSESSIONID",
    "TELEGRAM_BOT_TOKEN",
    "X_AUTH_TOKEN",
    "X_CT0",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
    "X_API_KEY",
    "X_API_KEY_SECRET",
    "X_BEARER_TOKEN",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".dump",
    ".age",
}
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "telegram_bot_token": re.compile(rb"\b\d{7,12}:[A-Za-z0-9_-]{30,}\b"),
    "anthropic_api_key": re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "openai_api_key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}\b"),
    "google_api_key": re.compile(rb"\bAIza[A-Za-z0-9_-]{30,}\b"),
}


def git(*args: str, check: bool = True) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def parse_env(payload: bytes) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in payload.decode("utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        parsed[name.strip()] = value.strip().strip("\"'")
    return parsed


def scan_tracked_files() -> tuple[int, list[str]]:
    tracked = [
        item.decode("utf-8", errors="surrogateescape")
        for item in git(
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ).split(b"\0")
        if item
    ]
    findings: list[str] = []
    for relative in tracked:
        path = ROOT / relative
        lowered = relative.lower()
        if (
            Path(lowered).name == ".env"
            or Path(lowered).suffix in FORBIDDEN_SUFFIXES
            or "static/generated_images/" in lowered
            and not lowered.endswith("/.gitkeep")
        ):
            findings.append(f"forbidden_artifact:{relative}")
        if not path.is_file():
            continue
        payload = path.read_bytes()
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(payload):
                findings.append(f"secret_shape:{label}:{relative}")
    return len(tracked), findings


def scan_history() -> tuple[int, list[str]]:
    active_path = ROOT / ".env"
    if not active_path.exists():
        return 0, []
    active = parse_env(active_path.read_bytes())
    prefix = git("rev-parse", "--show-prefix").decode().strip()
    env_path = f"{prefix}.env"
    commits = [
        line
        for line in git("log", "--all", "--format=%H", "--", ".env")
        .decode()
        .splitlines()
        if line
    ]
    matched: set[str] = set()
    for commit in commits:
        result = subprocess.run(
            ["git", "show", f"{commit}:{env_path}"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode:
            continue
        historical = parse_env(result.stdout)
        for name in SECRET_NAMES:
            current_value = active.get(name, "")
            if len(current_value) >= 8 and historical.get(name) == current_value:
                matched.add(name)
    return len(commits), sorted(matched)


def main() -> int:
    tracked_count, current_findings = scan_tracked_files()
    history_count, active_history_matches = scan_history()
    print(f"tracked_files={tracked_count}")
    print(f"working_tree_findings={len(current_findings)}")
    for finding in current_findings:
        print(f"  {finding}")
    print(f"historical_env_commits={history_count}")
    print(f"active_secrets_found_in_history={len(active_history_matches)}")
    for name in active_history_matches:
        print(f"  {name}")
    return 1 if current_findings or active_history_matches else 0


if __name__ == "__main__":
    sys.exit(main())
