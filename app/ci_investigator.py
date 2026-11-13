"""Read-only, evidence-based CI failure detection."""

import re


def analyze_log(log_text: str) -> dict:
    """Classify known failures without executing commands or exposing logs."""
    if not isinstance(log_text, str):
        raise TypeError("log_text must be a string")

    # Bound processing and avoid returning raw potentially sensitive logs.
    log = log_text[-200_000:]
    lower = log.lower()

    # The final Jenkins build result takes precedence over old log messages.
    final_statuses = re.findall(
        r"(?m)^Finished:\s+(SUCCESS|FAILURE|UNSTABLE|ABORTED|NOT_BUILT)\s*$",
        log,
    )

    if final_statuses and final_statuses[-1] == "SUCCESS":
        return {
            "status": "success",
            "category": None,
            "confidence": "reported",
            "evidence": ["Jenkins reported a successful build."],
            "probable_cause": None,
            "recommended_action": None,
            "automatic_changes": False,
        }

    # Ruff import-order failure: only accept explicit failed Jenkins builds.
    if final_statuses and final_statuses[-1] == "FAILURE" and re.search(
        r"(?m)^\s*I001\b", log
    ):
        paths = list(dict.fromkeys(re.findall(
            r"(?m)^\s*-->\s+((?:app|tests)/[A-Za-z0-9_./-]+\.py):\d+:\d+",
            log,
        )))
        paths = [path for path in paths if ".." not in path.split("/")][:10]
        return {
            "status": "failure_detected",
            "category": "code_quality",
            "confidence": "heuristic",
            "evidence": ["Jenkins failure includes Ruff I001 import-order diagnostics."],
            "candidate_files": paths,
            "probable_cause": "Ruff identified unsorted Python imports.",
            "recommended_action": "Review a local Ruff import-sort preview.",
            "automatic_changes": False,
        }

    rules = [
        {
            "category": "image_pull_failure",
            "matches": ["imagepullbackoff", "failed to pull image"],
            "cause": "Kubernetes cannot retrieve the requested image.",
            "action": (
                "Inspect Pod events, image digest, local containerd "
                "references, and registry authentication."
            ),
            "evidence": "Kubernetes reported an image pull failure.",
        },
        {
            "category": "container_vulnerability",
            "matches": ["trivy", "cve-", "vulnerability"],
            "cause": "The security scan detected a potential vulnerability.",
            "action": (
                "Inspect the Trivy findings and affected packages. "
                "Apply supported fixes and rerun the scan."
            ),
            "evidence": "Trivy and vulnerability indicators were detected.",
        },
        {
            "category": "secret_detection",
            "matches": ["gitleaks", "leaks found"],
            "cause": "Gitleaks reported potential exposed credentials.",
            "action": (
                "Review the findings, revoke genuine leaked credentials, "
                "and document verified false positives precisely."
            ),
            "evidence": "Gitleaks reported suspected secrets.",
        },
        {
            "category": "signature_verification",
            "matches": ["cosign", "verification failed"],
            "cause": "An artifact signature or attestation could not be verified.",
            "action": (
                "Check the image digest, signing public key, "
                "signature identity, and verification evidence."
            ),
            "evidence": "Cosign verification failure indicators were detected.",
        },
    ]

    for rule in rules:
        if all(term in lower for term in rule["matches"]):
            return {
                "status": "failure_detected",
                "category": rule["category"],
                "confidence": "heuristic",
                "evidence": [rule["evidence"]],
                "probable_cause": rule["cause"],
                "recommended_action": rule["action"],
                "automatic_changes": False,
            }

    if re.search(r"(?m)^Finished:\s+SUCCESS\s*$", log):
        return {
            "status": "success",
            "category": None,
            "confidence": "reported",
            "evidence": ["Jenkins reported a successful build."],
            "probable_cause": None,
            "recommended_action": None,
            "automatic_changes": False,
        }

    return {
        "status": "needs_investigation",
        "category": "unknown",
        "confidence": "low",
        "evidence": [],
        "probable_cause": None,
        "recommended_action": "Review the failed Jenkins stage and diagnostic output.",
        "automatic_changes": False,
    }
