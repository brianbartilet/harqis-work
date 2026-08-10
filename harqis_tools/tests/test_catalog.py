import json
import subprocess
import sys

import pytest

from harqis_tools.catalog import APP_CATALOG, get_app_spec, is_write_tool
from harqis_tools.cli import run
from agents.projects.permissions.enforcer import PermissionDenied


def test_catalog_keys_and_registrars_are_unique():
    keys = [spec.key for spec in APP_CATALOG]
    registrars = [spec.registrar for spec in APP_CATALOG]
    assert len(keys) == len(set(keys))
    assert len(registrars) == len(set(registrars))


def test_catalog_preserves_legacy_aliases():
    assert get_app_spec("Knowledge / RAG").key == "knowledge"
    assert get_app_spec("anthropic").key == "antropic"
    assert get_app_spec("OpenAI").key == "open_ai"


def test_apps_discovery_stays_under_context_budget():
    payload = json.dumps(run(["apps"]), separators=(",", ":"))
    assert len(payload) < 8_000  # comfortably below the ~2,000-token target


def test_apps_discovery_does_not_import_application_modules():
    code = (
        "import sys; from harqis_tools.cli import run; run(['apps']); "
        "print(any(n.startswith('apps.trello') or n.startswith('apps.ynab') "
        "for n in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "False"


def test_command_stdout_is_one_json_envelope():
    completed = subprocess.run(
        [sys.executable, "-m", "harqis_tools", "commands", "scryfall"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["result"]


@pytest.mark.parametrize("app", ["trello", "ynab", "scryfall"])
def test_representative_apps_expose_cli_commands(app):
    commands = run(["commands", app])
    assert commands
    assert all("name" in command and "write" in command for command in commands)


def test_cli_schema_preserves_mcp_tool_name():
    schema = run(["schema", "trello", "create_trello_card"])
    assert schema["name"] == "create_trello_card"
    assert schema["write"] is True
    assert "list_id" in schema["input_schema"]["properties"]


def test_cli_blocks_write_without_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("HARQIS_CLI_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    with pytest.raises(PermissionDenied, match="--confirm-write"):
        run([
            "call", "trello", "create_trello_card",
            "--input", '{"list_id":"x","name":"blocked"}',
        ])
    assert (tmp_path / "audit.jsonl").exists()


def test_cli_profile_blocks_unselected_app_before_execution(tmp_path, monkeypatch):
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "id: agent:test\nname: Test\ntools:\n  allowed: [read_file]\n  mcp_apps: [scryfall]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARQIS_CLI_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    with pytest.raises(PermissionDenied, match="not in the allowed list"):
        run([
            "call", "trello", "create_trello_card",
            "--input", '{"list_id":"x","name":"blocked"}',
            "--confirm-write", "--profile", str(profile),
        ])


def test_write_classification_is_conservative():
    assert is_write_tool("create_trello_card")
    assert is_write_tool("send_telegram_message")
    assert is_write_tool("complete_google_task")
    assert is_write_tool("emulator_adb_shell")
    assert is_write_tool("git_checkout")
    assert is_write_tool("vote_reddit")
    assert not is_write_tool("get_scryfall_card")
