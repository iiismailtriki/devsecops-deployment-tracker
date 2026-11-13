"""Poll Jenkins for new failures and launch bounded, read-only Groq investigations.

No Jenkins configuration changes or repository writes are performed.
"""

import argparse
import getpass
import hashlib
import json
import os
import time
from pathlib import Path

import requests

from app.groq_agent import call_groq, run_groq_agent
from app.jenkins_client import JenkinsClient

DEFAULT_STATE = Path.home() / ".local/state/devsecops-agent/seen.json"
DEFAULT_REPORTS = Path.home() / ".local/state/devsecops-agent/reports"


class SingleBuildClient:
    """Expose only the new failed build to the model's existing tools."""

    def __init__(self, jenkins, build):
        self.jenkins = jenkins
        self.build = build

    def failed_builds(self):
        return [self.build]

    def console_log(self, url):
        if url != self.build["url"]:
            raise ValueError("Build is not in the allowed investigation scope")
        return self.jenkins.console_log(url)


def save_private(path, content):
    """Write state/reports without leaving secrets in the repository."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def get_state(path):
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(branch, str) and type(number) is int
        for branch, number in raw.items()
    ):
        raise ValueError("Watcher state file has an invalid format")
    return raw


def valid_builds(jenkins):
    builds = []
    for item in jenkins.failed_builds():
        if (
            isinstance(item, dict)
            and isinstance(item.get("branch"), str)
            and type(item.get("number")) is int
            and isinstance(item.get("url"), str)
        ):
            builds.append(item)
    return builds


def poll_once(jenkins, investigate, state_path, reports_dir, process_existing=False):
    """Handle at most one new failure per poll; do not reprocess history."""
    builds = valid_builds(jenkins)
    seen = get_state(state_path)
    if seen is None and not process_existing:
        save_private(
            state_path,
            json.dumps({b["branch"]: b["number"] for b in builds}, indent=2),
        )
        return "Initialized baseline; waiting for a new Jenkins failure."
    if seen is None:
        seen = {}

    pending = [
        b for b in builds
        if process_existing or b["number"] > seen.get(b["branch"], -1)
    ]
    if not pending:
        return "No new failed builds."

    build = pending[0]
    print(f"Investigating branch {build['branch']!r} build #{build['number']}")
    try:
        report = investigate(SingleBuildClient(jenkins, build))
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
        # Mark the failed attempt as seen to avoid repeated API charges on every poll.
        report = f"Investigation could not complete: {type(exc).__name__}. Retry manually."

    safe_id = hashlib.sha256(
        f"{build['branch']}:{build['number']}".encode()
    ).hexdigest()[:16]
    filename = reports_dir / f"failure-{safe_id}.md"
    save_private(
        filename,
        f"# Jenkins CI investigation\n\n"
        f"Build branch: {build['branch']}\n\n"
        f"Build number: {build['number']}\n\n{report}\n",
    )
    seen[build["branch"]] = max(seen.get(build["branch"], -1), build["number"])
    save_private(state_path, json.dumps(seen, indent=2))
    return f"Investigation saved: {filename}"


def main():
    parser = argparse.ArgumentParser(description="Watch Jenkins failures with Groq AI")
    parser.add_argument("--once", action="store_true", help="Check once and stop")
    parser.add_argument(
        "--process-existing", action="store_true",
        help="Investigate an old failure for a demo (otherwise baseline existing history)",
    )
    parser.add_argument("--interval", type=int, default=60, help="Seconds between polls (min 30)")
    args = parser.parse_args()
    if args.interval < 30:
        parser.error("interval must be at least 30 seconds")

    username = input("Jenkins username [ismail]: ").strip() or "ismail"
    jenkins_token = getpass.getpass("Jenkins API token: ")
    groq_key = os.getenv("GROQ_API_KEY") or getpass.getpass("Groq API key: ")
    if not jenkins_token or not groq_key:
        print("Missing credentials; no requests made.")
        return
    jenkins = JenkinsClient(username, jenkins_token)

    def investigate(selected_client):
        return run_groq_agent(
            selected_client,
            lambda messages, choice: call_groq(messages, groq_key, choice),
        )

    print("Watching Jenkins failures; Ctrl+C to stop. Read-only mode.")
    try:
        while True:
            try:
                print(poll_once(
                    jenkins, investigate, DEFAULT_STATE, DEFAULT_REPORTS,
                    process_existing=args.process_existing,
                ))
            except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
                print(f"Poll failed: {type(exc).__name__}")
            if args.once:
                break
            # Avoid constantly investigating historical builds in demo mode.
            args.process_existing = False
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Watcher stopped.")


if __name__ == "__main__":
    main()
