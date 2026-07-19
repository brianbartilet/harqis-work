from modules.applications.test_runner import TestRun, parse_summary, redact_output


def test_test_run_public_dict_excludes_process():
    run = TestRun(id="abc", app="aaa", mode="safe", targets=["apps/aaa/tests"])

    assert "process" not in run.public_dict()


def test_output_redaction_masks_loaded_secrets(monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_TOKEN", "sensitive-token-value")

    output = redact_output(
        "token=sensitive-token-value password=visible authorization: bearer-value"
    )

    assert "sensitive-token-value" not in output
    assert "bearer-value" not in output
    assert output.count("[REDACTED]") >= 2


def test_pytest_summary_parsing():
    assert parse_summary("12 passed, 2 failed, 3 skipped in 1.2s") == {
        "passed": 12,
        "failed": 2,
        "skipped": 3,
    }
