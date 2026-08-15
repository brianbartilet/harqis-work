from apps.android_emulator.client import CmdResult
from apps.plaud.references.companion import (
    CompanionConfig,
    PlaudCompanionController,
    _parse_broadcast_payload,
)


def _result(payload: str, *, ok: bool = True) -> CmdResult:
    escaped = payload.replace("\\", "\\\\").replace('"', '\\"')
    return CmdResult(
        ok=ok,
        returncode=0 if ok else 1,
        stdout=f'Broadcast completed: result=0, data="{escaped}"',
        stderr="",
    )


def test_parse_broadcast_payload():
    parsed = _parse_broadcast_payload(
        'Broadcast completed: result=0, data="{\\"success\\":true,\\"state\\":\\"idle\\"}"'
    )
    assert parsed == {"success": True, "state": "idle"}


def test_missing_configuration_fails_closed():
    controller = PlaudCompanionController(
        CompanionConfig(serial="", token=""),
        adb_runner=lambda *args, **kwargs: None,
    )
    result = controller.command("start")
    assert result["success"] is False
    assert "not configured" in result["error"]


def test_command_uses_explicit_component_and_redacts_token_from_result():
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return _result(
            '{"success":true,"state":"recording","active_triggers":["calendar"]}'
        )

    controller = PlaudCompanionController(
        CompanionConfig(serial="phone-1", token="secret-control-token"),
        adb_runner=runner,
    )
    result = controller.command("start", timeout_seconds=0, poll_interval=0)

    assert result["success"] is True
    assert result["verified"] is True
    assert calls[0][:3] == ["-s", "phone-1", "shell"]
    assert "-n" in calls[0]
    assert "com.harqis.plaudcompanion" in calls[0][calls[0].index("-n") + 1]
    assert "secret-control-token" not in str(result)


def test_invalid_action_never_calls_adb():
    calls = []
    controller = PlaudCompanionController(
        CompanionConfig(serial="phone-1", token="token"),
        adb_runner=lambda *args, **kwargs: calls.append(args),
    )
    result = controller.command("factory-reset")
    assert result["success"] is False
    assert calls == []


def test_stop_releases_calendar_without_stopping_location_recording():
    def runner(args, **kwargs):
        action = args[args.index("action") + 1]
        if action == "stop":
            return _result(
                '{"success":true,"state":"recording","active_triggers":["calendar","location"]}'
            )
        return _result(
            '{"success":true,"state":"recording","active_triggers":["location"]}'
        )

    controller = PlaudCompanionController(
        CompanionConfig(serial="phone-1", token="token"),
        adb_runner=runner,
    )
    result = controller.command("stop", timeout_seconds=0, poll_interval=0)

    assert result["success"] is True
    assert result["verified"] is True
    assert result["state"] == "recording"
    assert result["active_triggers"] == ["location"]
