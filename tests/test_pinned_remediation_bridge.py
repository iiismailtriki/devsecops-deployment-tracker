"""Fail-closed tests for commit-pinned remediation."""

from app import pinned_remediation_bridge as bridge

SHA = "a" * 40
VERIFIED = {"status": "verified", "commit": SHA, "source": "jenkins_lastBuiltRevision"}


def test_rejects_unverified_revision_without_preview(monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("must not preview")

    monkeypatch.setattr(bridge, "preview_committed_import_fix", forbidden)
    result = bridge.safe_pinned_import_preview(
        "code_quality", ["app/main.py"], {"status": "unavailable"},
        {"path": "app/main.py"}, tmp_path
    )
    assert "error" in result


def test_rejects_wrong_category_and_unlisted_file(tmp_path):
    assert "error" in bridge.safe_pinned_import_preview(
        "secret_detection", ["app/main.py"], VERIFIED, {"path": "app/main.py"}, tmp_path
    )
    assert "error" in bridge.safe_pinned_import_preview(
        "code_quality", ["app/a.py"], VERIFIED, {"path": "app/main.py"}, tmp_path
    )


def test_rejects_non_jenkins_source_or_incomplete_sha(tmp_path):
    for revision in (
        {"status": "verified", "commit": SHA, "source": "model"},
        {"status": "verified", "commit": "a" * 12, "source": "jenkins_lastBuiltRevision"},
    ):
        assert "error" in bridge.safe_pinned_import_preview(
            "code_quality", ["app/a.py"], revision, {"path": "app/a.py"}, tmp_path
        )


def test_pinned_preview_returns_metadata_only(monkeypatch, tmp_path):
    calls = []

    def fake_preview(repo, commit, category, paths, path):
        calls.append((repo, commit, category, paths, path))
        return {
            "commit": SHA, "path": "app/a.py", "changed": True,
            "diff": "SECRET_SOURCE_PATCH_SHOULD_NOT_LEAK",
            "applied_to_repository": False, "tests_executed": False,
        }

    monkeypatch.setattr(bridge, "preview_committed_import_fix", fake_preview)
    result = bridge.safe_pinned_import_preview(
        "code_quality", ["app/a.py"], VERIFIED, {"path": "app/a.py"}, tmp_path
    )
    assert calls == [(tmp_path, SHA, "code_quality", ["app/a.py"], "app/a.py")]
    assert result["changed"] is True
    assert result["review_required"] is True
    assert "SECRET_SOURCE_PATCH_SHOULD_NOT_LEAK" not in str(result)
    assert "diff" not in result


def test_fail_closed_when_revision_engine_refuses(monkeypatch, tmp_path):
    monkeypatch.setattr(
        bridge, "preview_committed_import_fix", lambda *_: {"error": "not found"}
    )
    result = bridge.safe_pinned_import_preview(
        "code_quality", ["app/a.py"], VERIFIED, {"path": "app/a.py"}, tmp_path
    )
    assert result == {"error": "Pinned revision preview refused"}
