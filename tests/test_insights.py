from app.insights import analyze_dependencies, analyze_git_archive


def test_dependency_inventory_marks_unpinned_versions():
    result = analyze_dependencies([
        ("requirements.txt", "flask>=3.0\nreportlab==4.0.0\n"),
        ("package.json", '{"dependencies":{"vue":"latest","axios":"^1.0.0"}}'),
    ])
    assert result["manifest_count"] == 2
    assert result["dependency_count"] == 4
    assert result["unpinned_count"] == 3


def test_git_evidence_reports_when_archive_has_no_history():
    result = analyze_git_archive(b"not-a-zip")
    assert result["included"] is False
    assert result["commit_count"] == 0
