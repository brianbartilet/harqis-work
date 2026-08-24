import pytest

from workflows.second_brain.hermes import HermesUnavailable, interpret_context


def test__hermes_rejects_non_loopback_endpoint(monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_HERMES_BASE_URL", "https://agent.example.test/v1")
    monkeypatch.setenv("SECOND_BRAIN_HERMES_API_KEY", "configured")

    with pytest.raises(HermesUnavailable, match="loopback"):
        interpret_context([])


def test__hermes_requires_server_side_bearer(monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_HERMES_BASE_URL", "http://127.0.0.1:8643/v1")
    monkeypatch.delenv("SECOND_BRAIN_HERMES_API_KEY", raising=False)

    with pytest.raises(HermesUnavailable, match="loopback"):
        interpret_context([])
