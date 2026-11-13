"""Read-only Jenkins API collector for the DevSecOps agent."""

import getpass
import re
from urllib.parse import urlsplit

import requests

from app.ci_investigator import analyze_log

BASE_URL = "http://127.0.0.1:8080"
PIPELINE = "deployment-tracker-multibranch"
MAX_LOG_BYTES = 1_000_000


class JenkinsClient:
    def __init__(self, username, token):
        self.session = requests.Session()
        self.session.auth = (username, token)
        self.session.trust_env = False

    def failed_builds(self):
        response = self.session.get(
            f"{BASE_URL}/job/{PIPELINE}/api/json",
            params={
                "tree": "jobs[name,lastFailedBuild[number,url]]"
            },
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Jenkins API HTTP {response.status_code}")

        builds = []
        for job in response.json().get("jobs", []):
            failed = job.get("lastFailedBuild")
            if failed:
                builds.append({
                    "branch": job["name"],
                    "number": failed["number"],
                    "url": failed["url"],
                })
        return builds

    def console_log(self, build_url):
        parsed = urlsplit(build_url)
        path = parsed.path

        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.port != 8080
            or not re.fullmatch(
                rf"/job/{re.escape(PIPELINE)}/job/[^/]+/\d+/?",
                path,
            )
        ):
            raise ValueError("Untrusted Jenkins build URL")

        response = self.session.get(
            f"{BASE_URL}{path.rstrip('/')}/consoleText",
            timeout=15,
            stream=True,
            allow_redirects=False,
        )

        try:
            if response.status_code != 200:
                raise RuntimeError(
                    f"Jenkins console HTTP {response.status_code}"
                )

            content = bytearray()
            truncated = False

            for chunk in response.iter_content(chunk_size=8192):
                remaining = MAX_LOG_BYTES - len(content)
                if len(chunk) > remaining:
                    content.extend(chunk[:remaining])
                    truncated = True
                    break
                content.extend(chunk)

            return content[-200_000:].decode(
                "utf-8", errors="replace"
            ), truncated
        finally:
            response.close()


def main():
    username = input("Jenkins username [ismail]: ").strip() or "ismail"
    token = getpass.getpass("Jenkins API token: ")

    client = JenkinsClient(username, token)

    try:
        builds = client.failed_builds()
        print(f"\nFound {len(builds)} branches with previous failed builds.")

        for build in builds[:3]:
            print(
                f"\nBranch: {build['branch']!r} "
                f"| Failed build: #{build['number']}"
            )
            try:
                log, truncated = client.console_log(build["url"])
                result = analyze_log(log)

                if result["status"] == "success":
                    result = {
                        "status": "needs_investigation",
                        "category": "conflicting_log_evidence",
                        "probable_cause": None,
                        "recommended_action": (
                            "Check the authoritative Jenkins build result."
                        ),
                    }

                print(f"Status: {result['status']}")
                print(f"Category: {result['category']}")
                print(f"Possible cause: {result['probable_cause']}")
                print(f"Action: {result['recommended_action']}")

                if truncated:
                    print("Warning: log truncated; analysis incomplete.")
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                print(f"Could not inspect build: {type(exc).__name__}")

    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"Jenkins API error: {type(exc).__name__}")


if __name__ == "__main__":
    main()
