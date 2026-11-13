from app.ci_investigator import analyze_log


def test_trivy_vulnerability():
    result = analyze_log(
        "Trivy found a vulnerability: CVE-2026-12345\nFinished: FAILURE"
    )
    assert result["category"] == "container_vulnerability"
    assert result["status"] == "failure_detected"


def test_kubernetes_image_pull():
    result = analyze_log(
        "ImagePullBackOff: failed to pull image\n"
        "401 Unauthorized"
    )
    assert result["category"] == "image_pull_failure"


def test_gitleaks():
    result = analyze_log(
        "Gitleaks scan: 2 leaks found\nFinished: FAILURE"
    )
    assert result["category"] == "secret_detection"


def test_cosign():
    result = analyze_log(
        "Cosign: signature verification failed"
    )
    assert result["category"] == "signature_verification"


def test_successful_build():
    result = analyze_log("Finished: SUCCESS")
    assert result["status"] == "success"


def test_unknown_failure():
    result = analyze_log("Unexpected build error")
    assert result["status"] == "needs_investigation"


def test_invalid_input():
    import pytest

    with pytest.raises(TypeError):
        analyze_log(None)


def test_does_not_return_raw_secrets():
    result = analyze_log(
        "ImagePullBackOff: failed to pull image\n"
        "Authorization: Bearer secret-token-123"
    )
    assert "secret-token-123" not in str(result)
    assert result["automatic_changes"] is False


def test_success_overrides_old_vulnerability_messages():
    result = analyze_log(
        "Trivy found a vulnerability: CVE-2026-12345\n"
        "Vulnerability fixed\n"
        "Finished: SUCCESS"
    )
    assert result["status"] == "success"
    assert result["category"] is None


def test_final_failure_overrides_previous_success():
    result = analyze_log(
        "Finished: SUCCESS\n"
        "Trivy found a vulnerability: CVE-2026-12345\n"
        "Finished: FAILURE"
    )
    assert result["category"] == "container_vulnerability"
