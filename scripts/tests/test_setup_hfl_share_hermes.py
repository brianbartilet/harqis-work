from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def managed_share(tmp_path, monkeypatch):
    setup = load_setup_module()
    home = tmp_path / "hermes"
    profile = home / "profiles" / "sharecorpus"
    profile.mkdir(parents=True, mode=0o700)
    setup._write_private_text(profile / ".harqis-share-profile", "managed\n")
    setup._write_private_text(profile / "config.yaml", setup.json.dumps(
        setup.locked_down_profile_config("gpt-5.6-sol")
    ))
    setup._write_private_text(profile / ".env", setup._dotenv_text(
        setup._profile_env_values(8643, "fixture-key")
    ))
    setup._write_private_text(profile / "auth.json", "{}\n")
    app_env = tmp_path / "apps.env"
    setup.upsert_env_file(app_env, setup._harqis_env_values(8643, "fixture-key", 120_000))
    monkeypatch.setattr(setup, "_oauth_ready", lambda *args: True)
    args = setup._parser().parse_args([
        "--check", "--hermes-home", str(home), "--harqis-env", str(app_env)
    ])
    return setup, args, profile


def test_check_accepts_hermes_migrated_yaml_without_rewriting(managed_share, monkeypatch):
    setup, args, profile = managed_share
    config = setup.locked_down_profile_config(args.model)
    config["_config_version"] = 50
    path = profile / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    before = {p: p.read_bytes() for p in args.hermes_home.rglob("*") if p.is_file()}
    checked = []
    monkeypatch.setattr(setup, "_check_api", lambda **kw: checked.append(kw))

    setup._check_setup(args)

    assert checked == [{"base_url": "http://127.0.0.1:8643/v1",
                        "api_key": "fixture-key", "expected_model": "share-corpus"}]
    assert before == {p: p.read_bytes() for p in args.hermes_home.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", [
    {"gateway": {}},
    {"gateway": {"standalone": False}},
    {"gateway": {"standalone": "true"}},
    {"gateway": {"standalone": 1}},
    {"memory": {"memory_enabled": True, "user_profile_enabled": False}},
    {"platform_toolsets": {"api_server": ["terminal"]}},
    {"unknown_setting": True},
    {"_config_version": "invalid"},
])
def test_check_rejects_unsafe_migrated_config_before_api(managed_share, monkeypatch, change):
    setup, args, profile = managed_share
    config = setup.locked_down_profile_config(args.model)
    config.update(change)
    (profile / "config.yaml").write_text(yaml.safe_dump(config))
    monkeypatch.setattr(setup, "_check_api", lambda **kw: pytest.fail("unsafe API probe"))
    with pytest.raises(RuntimeError, match="config"):
        setup._check_setup(args)


@pytest.fixture
def loopback_api():
    """Real HTTP boundary; no Hermes, OAuth, provider traffic or production port."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    state = {"model": "share-corpus", "tools": False, "auth": True,
             "cors": False, "redirect": False, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            state["requests"].append(self.path)
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "/must-not-follow")
                self.end_headers()
                return
            if self.path != "/v1/health" and (
                not state["auth"] or self.headers.get("Authorization") != "Bearer fixture-key"
            ):
                self.send_response(401)
                self.end_headers()
                return
            payloads = {
                "/v1/health": {"status": "ok"},
                "/v1/models": {"data": [{"id": state["model"]}]},
                "/v1/capabilities": {"model": state["model"], "features": {"cors": state["cors"]}},
                "/v1/toolsets": {"data": [{"name": "terminal", "enabled": state["tools"]}]},
            }
            if self.path not in payloads:
                self.send_response(404)
                self.end_headers()
                return
            import json
            body = json.dumps(payloads[self.path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def point_managed_share_at_port(managed_share, port):
    setup, args, profile = managed_share
    args.port = port
    setup.upsert_env_file(profile / ".env", setup._profile_env_values(port, "fixture-key"))
    setup.upsert_env_file(args.harqis_env, setup._harqis_env_values(port, "fixture-key", 120_000))


def test_readiness_checks_real_authenticated_app_endpoint(managed_share, loopback_api):
    setup, args, _ = managed_share
    port, state = loopback_api
    point_managed_share_at_port(managed_share, port)
    setup._check_setup(args)
    assert state["requests"] == ["/v1/health", "/v1/models", "/v1/capabilities", "/v1/toolsets"]


@pytest.mark.parametrize("change", [
    {"model": "default-private-agent"}, {"tools": True}, {"auth": False},
    {"cors": True}, {"redirect": True},
])
def test_readiness_rejects_live_unsafe_or_wrong_endpoint(
    managed_share, loopback_api, monkeypatch, change
):
    setup, args, _ = managed_share
    port, state = loopback_api
    state.update(change)
    point_managed_share_at_port(managed_share, port)
    monkeypatch.setattr(setup.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="API health check failed"):
        setup._check_setup(args)
    assert "/must-not-follow" not in state["requests"]


def test_gateway_success_cannot_mask_missing_api_listener(managed_share, monkeypatch, capsys):
    import socket
    from types import SimpleNamespace

    setup, args, _ = managed_share
    commands = []

    def gateway_success(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="served by default multiplexer", stderr="")

    monkeypatch.setattr(setup, "_run", gateway_success)
    monkeypatch.setattr(setup.time, "sleep", lambda seconds: None)
    # Bound real network timeouts too: some OSes time out rather than refuse
    # connections to a reserved-but-not-listening port.
    build_opener = setup.urllib.request.build_opener

    def bounded_opener(*handlers):
        opener = build_opener(*handlers)
        original_open = opener.open
        opener.open = lambda request, timeout: original_open(request, timeout=min(timeout, 0.1))
        return opener

    monkeypatch.setattr(setup.urllib.request, "build_opener", bounded_opener)
    # Hold the ephemeral port without listening: deterministic refusal, no port race.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        point_managed_share_at_port(managed_share, port)
        for action in ("--check", "--start"):
            commands.clear()
            with pytest.raises(RuntimeError, match="API health check failed"):
                setup.main([action, "--hermes-home", str(args.hermes_home),
                            "--harqis-env", str(args.harqis_env), "--port", str(port)])
            assert "checks passed" not in capsys.readouterr().out
            if action == "--check":
                assert commands == []  # A health check never repairs or restarts.
            else:
                assert len(commands) == 2
                assert all(command[1:3] == ["-p", "sharecorpus"] for command in commands)


def load_setup_module():
    path = Path(__file__).resolve().parents[1] / "agents" / "hfl" / "setup_hfl_share_hermes.py"
    spec = importlib.util.spec_from_file_location("setup_hfl_share_hermes_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_locked_down_profile_config_has_no_tools_memory_or_fallbacks():
    setup = load_setup_module()

    config = setup.locked_down_profile_config("gpt-5.6-sol")

    assert config["model"] == {
        "default": "gpt-5.6-sol",
        "provider": "openai-codex",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_mode": "codex_responses",
    }
    assert config["fallback_providers"] == []
    assert config["memory"] == {
        "memory_enabled": False,
        "user_profile_enabled": False,
    }
    assert config["platform_toolsets"] == {"api_server": []}
    assert config["platforms"] == {}
    # A shared host claiming this profile does not serve its dedicated port.
    assert config["gateway"] == {"standalone": True}


def test_upsert_env_is_idempotent_private_and_preserves_unrelated_values(tmp_path):
    setup = load_setup_module()
    env_path = tmp_path / ".env"
    env_path.write_text("# existing\nOTHER=value\nHFL_SHARE_PROVIDER=anthropic\n")

    values = {
        "HFL_SHARE_PROVIDER": "hermes",
        "HFL_SHARE_HERMES_API_KEY": "server-secret",
    }
    setup.upsert_env_file(env_path, values)
    setup.upsert_env_file(env_path, values)

    text = env_path.read_text()
    assert "# existing\n" in text
    assert "OTHER=value\n" in text
    assert text.count("HFL_SHARE_PROVIDER=hermes") == 1
    assert text.count("HFL_SHARE_HERMES_API_KEY=server-secret") == 1
    if os.name != "nt":
        assert env_path.stat().st_mode & 0o777 == 0o600


def test_dry_run_reports_plan_without_creating_profile_or_env(tmp_path, capsys):
    setup = load_setup_module()
    hermes_home = tmp_path / "hermes"
    harqis_env = tmp_path / "apps.env"

    result = setup.main(
        [
            "--hermes-home",
            str(hermes_home),
            "--harqis-env",
            str(harqis_env),
        ]
    )

    assert result == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not hermes_home.exists()
    assert not harqis_env.exists()


def test_apply_creates_isolated_profile_and_never_prints_generated_key(
    tmp_path, monkeypatch, capsys
):
    setup = load_setup_module()
    hermes_home = tmp_path / "hermes"
    harqis_env = tmp_path / "repo" / ".env" / "apps.env"
    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def run(command, *, env, check=False):
        calls.append(command)
        if command[1:3] == ["profile", "create"]:
            (hermes_home / "profiles" / "sharecorpus").mkdir(parents=True)
        if "auth" in command and "status" in command:
            return Result(returncode=0, stdout="openai-codex: logged out")
        return Result()

    monkeypatch.setattr(setup, "_run", run, raising=False)
    monkeypatch.setattr(
        setup.secrets,
        "token_urlsafe",
        lambda size: "generated-private-key",
        raising=False,
    )

    result = setup.main(
        [
            "--apply",
            "--hermes-home",
            str(hermes_home),
            "--harqis-env",
            str(harqis_env),
        ]
    )

    assert result == 0
    profile = hermes_home / "profiles" / "sharecorpus"
    config = setup.json.loads((profile / "config.yaml").read_text())
    assert config == setup.locked_down_profile_config("gpt-5.6-sol")
    assert not (profile / "skills").exists()
    assert "API_SERVER_HOST=127.0.0.1" in (profile / ".env").read_text()
    assert "API_SERVER_CORS_ORIGINS" not in (profile / ".env").read_text()
    assert "API_SERVER_KEY=generated-private-key" in (profile / ".env").read_text()
    assert "HFL_SHARE_PROVIDER=hermes" in harqis_env.read_text()
    assert "HFL_SHARE_MAX_CONTEXT_CHARS=120000" in harqis_env.read_text()
    assert "HFL_SHARE_HERMES_API_KEY=generated-private-key" in harqis_env.read_text()
    if os.name != "nt":
        assert (profile / ".env").stat().st_mode & 0o777 == 0o600
        assert harqis_env.stat().st_mode & 0o777 == 0o600
    assert ["hermes", "profile", "create", "sharecorpus", "--no-skills", "--description", "Snapshot-only HARQIS Share Corpus inference"] in calls
    output = capsys.readouterr().out
    assert "generated-private-key" not in output
    assert "python scripts/agents/hfl/setup_hfl_share_hermes.py --login" in output
    assert "--hermes-home" in output and str(hermes_home) in output
    assert "--harqis-env" in output and str(harqis_env) in output


def test_apply_start_installs_gateway_only_after_oauth_and_checks_api(
    tmp_path, monkeypatch, capsys
):
    setup = load_setup_module()
    hermes_home = tmp_path / "hermes"
    profile = hermes_home / "profiles" / "sharecorpus"
    harqis_env = tmp_path / "repo" / ".env" / "apps.env"
    calls = []
    checked = []

    class Result:
        returncode = 0
        stdout = "openai-codex: logged in"
        stderr = ""

    def run(command, *, env, check=False):
        calls.append(command)
        if command[1:3] == ["profile", "create"]:
            profile.mkdir(parents=True)
            (profile / "auth.json").write_text("{}")
            (profile / "auth.json").chmod(0o600)
        return Result()

    monkeypatch.setattr(setup, "_run", run)
    monkeypatch.setattr(setup, "_check_api", lambda **kwargs: checked.append(kwargs), raising=False)
    monkeypatch.setattr(setup.secrets, "token_urlsafe", lambda size: "start-key")

    result = setup.main(
        [
            "--apply",
            "--start",
            "--hermes-home",
            str(hermes_home),
            "--harqis-env",
            str(harqis_env),
        ]
    )

    assert result == 0
    assert "API_SERVER_CORS_ORIGINS" not in (profile / ".env").read_text()
    assert ["hermes", "-p", "sharecorpus", "gateway", "install"] in calls
    assert ["hermes", "-p", "sharecorpus", "gateway", "restart"] in calls
    assert checked == [
        {
            "base_url": "http://127.0.0.1:8643/v1",
            "api_key": "start-key",
            "expected_model": "share-corpus",
        }
    ]
    assert "Hermes Share API is ready" in capsys.readouterr().out


def test_check_verifies_profile_environment_oauth_and_api_without_writes(
    tmp_path, monkeypatch, capsys
):
    setup = load_setup_module()
    hermes_home = tmp_path / "hermes"
    profile = hermes_home / "profiles" / "sharecorpus"
    profile.mkdir(parents=True)
    profile.chmod(0o700)
    (profile / ".harqis-share-profile").write_text("managed\n")
    (profile / "config.yaml").write_text(
        setup.json.dumps(setup.locked_down_profile_config("gpt-5.6-sol"))
    )
    setup.upsert_env_file(
        profile / ".env",
        setup._profile_env_values(8643, "check-key"),
    )
    setup._write_private_text(profile / "auth.json", "{}\n")
    harqis_env = tmp_path / "repo" / ".env" / "apps.env"
    setup.upsert_env_file(
        harqis_env,
        setup._harqis_env_values(8643, "check-key", 120_000),
    )
    checked = []

    class Result:
        returncode = 0
        stdout = "openai-codex: logged in"
        stderr = ""

    monkeypatch.setattr(setup, "_run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(setup, "_check_api", lambda **kwargs: checked.append(kwargs))

    result = setup.main(
        [
            "--check",
            "--hermes-home",
            str(hermes_home),
            "--harqis-env",
            str(harqis_env),
        ]
    )

    assert result == 0
    assert checked == [
        {
            "base_url": "http://127.0.0.1:8643/v1",
            "api_key": "check-key",
            "expected_model": "share-corpus",
        }
    ]
    assert "Configuration and API checks passed" in capsys.readouterr().out


def test_hermes_subprocess_environment_drops_proxy_platform_and_cors_values(
    tmp_path, monkeypatch
):
    setup = load_setup_module()
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://proxy.example:1080")
    monkeypatch.setenv("API_SERVER_CORS_ORIGINS", "https://unsafe.example")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "private-token")

    environment = setup._hermes_environment(tmp_path / "hermes")

    assert environment["HERMES_HOME"] == str(tmp_path / "hermes")
    assert environment["NO_PROXY"] == "127.0.0.1,::1"
    assert environment["no_proxy"] == "127.0.0.1,::1"
    assert "HTTP_PROXY" not in environment
    assert "ALL_PROXY" not in environment
    assert "API_SERVER_CORS_ORIGINS" not in environment
    assert "TELEGRAM_BOT_TOKEN" not in environment


def test_oauth_status_requires_logged_in_text_even_when_exit_code_is_zero(monkeypatch):
    setup = load_setup_module()

    class Result:
        returncode = 0
        stdout = "openai-codex: logged out"
        stderr = ""

    monkeypatch.setattr(setup, "_run", lambda *args, **kwargs: Result())

    assert setup._oauth_ready("sharecorpus", {}) is False


def test_login_uses_custom_hermes_home(tmp_path, monkeypatch):
    setup = load_setup_module()
    hermes_home = tmp_path / "custom-hermes"
    profile = hermes_home / "profiles" / "sharecorpus"
    profile.mkdir(parents=True)
    profile.chmod(0o700)
    (profile / ".harqis-share-profile").write_text("managed\n")
    (profile / "config.yaml").write_text(
        setup.json.dumps(setup.locked_down_profile_config("gpt-5.6-sol"))
    )
    setup._write_private_text(
        profile / ".env",
        setup._dotenv_text(setup._profile_env_values(8643, "login-key")),
    )
    harqis_env = tmp_path / "repo" / ".env" / "apps.env"
    setup.upsert_env_file(
        harqis_env,
        setup._harqis_env_values(8643, "login-key", 120_000),
    )
    captured = {}

    class Result:
        returncode = 0
        stdout = "openai-codex: logged in"
        stderr = ""

    def interactive(command, *, env):
        captured.update(command=command, environment=env)
        setup._write_private_text(profile / "auth.json", "{}\n")
        return Result()

    monkeypatch.setattr(setup, "_run_interactive", interactive)
    monkeypatch.setattr(setup, "_run", lambda *args, **kwargs: Result())

    result = setup.main(
        [
            "--login",
            "--hermes-home",
            str(hermes_home),
            "--harqis-env",
            str(harqis_env),
        ]
    )

    assert result == 0
    assert captured["environment"]["HERMES_HOME"] == str(hermes_home)
    assert captured["command"] == [
        "hermes",
        "-p",
        "sharecorpus",
        "auth",
        "add",
        "openai-codex",
        "--type",
        "oauth",
    ]


def test_env_update_rejects_symlinked_parent(tmp_path):
    import pytest

    setup = load_setup_module()
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable on this host: {exc}")

    with pytest.raises(ValueError, match="symlinked path component"):
        setup.upsert_env_file(linked_parent / "apps.env", {"SAFE": "value"})


def test_apply_refuses_even_marked_existing_profile(tmp_path):
    import pytest

    setup = load_setup_module()
    hermes_home = tmp_path / "hermes"
    profile = hermes_home / "profiles" / "sharecorpus"
    profile.mkdir(parents=True)
    (profile / ".harqis-share-profile").write_text("forged marker\n")

    with pytest.raises(RuntimeError, match="Refusing --apply"):
        setup.main(
            [
                "--apply",
                "--hermes-home",
                str(hermes_home),
                "--harqis-env",
                str(tmp_path / "apps.env"),
            ]
        )


def test_start_rejects_residual_plugin_state(tmp_path):
    import pytest

    setup = load_setup_module()
    hermes_home = tmp_path / "hermes"
    profile = hermes_home / "profiles" / "sharecorpus"
    (profile / "plugins").mkdir(parents=True)
    (profile / "plugins" / "private.py").write_text("secret")

    with pytest.raises(RuntimeError, match="plugins/"):
        setup.main(
            [
                "--start",
                "--hermes-home",
                str(hermes_home),
                "--harqis-env",
                str(tmp_path / "apps.env"),
            ]
        )


def test_api_check_disables_environment_proxies_and_requires_model(
    monkeypatch
):
    setup = load_setup_module()
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return setup.json.dumps(self.payload).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            if isinstance(request, str):
                return Response({"status": "ok"})
            if request.full_url.endswith("/models"):
                return Response({"data": [{"id": "share-corpus"}]})
            if request.full_url.endswith("/capabilities"):
                return Response(
                    {
                        "model": "share-corpus",
                        "features": {"cors": False},
                    }
                )
            return Response({"data": [{"name": "terminal", "enabled": False}]})

    def build_opener(*handlers):
        proxy_handlers = [
            handler
            for handler in handlers
            if isinstance(handler, setup.urllib.request.ProxyHandler)
        ]
        assert len(proxy_handlers) == 1
        assert proxy_handlers[0].proxies == {}
        assert any(isinstance(handler, setup._RejectRedirects) for handler in handlers)
        return Opener()

    monkeypatch.setattr(setup.urllib.request, "build_opener", build_opener)

    setup._check_api(
        base_url="http://127.0.0.1:8643/v1",
        api_key="check-key",
        expected_model="share-corpus",
    )

    assert len(calls) == 4


def test_check_rejects_group_readable_credentials(tmp_path, monkeypatch):
    import pytest

    if os.name == "nt":
        pytest.skip("Windows does not expose authoritative POSIX mode bits")

    setup = load_setup_module()
    hermes_home = tmp_path / "hermes"
    profile = hermes_home / "profiles" / "sharecorpus"
    profile.mkdir(parents=True)
    profile.chmod(0o700)
    (profile / ".harqis-share-profile").write_text("managed\n")
    (profile / "config.yaml").write_text(
        setup.json.dumps(setup.locked_down_profile_config("gpt-5.6-sol"))
    )
    setup._write_private_text(
        profile / ".env",
        setup._dotenv_text(setup._profile_env_values(8643, "check-key")),
    )
    setup._write_private_text(profile / "auth.json", "{}\n")
    harqis_env = tmp_path / "apps.env"
    setup.upsert_env_file(
        harqis_env,
        setup._harqis_env_values(8643, "check-key", 120_000),
    )
    (profile / ".env").chmod(0o640)

    with pytest.raises(RuntimeError, match="private permissions"):
        setup.main(
            [
                "--check",
                "--hermes-home",
                str(hermes_home),
                "--harqis-env",
                str(harqis_env),
            ]
        )


def test_api_check_rejects_additional_models_and_missing_toolset_data(monkeypatch):
    import pytest

    setup = load_setup_module()
    monkeypatch.setattr(setup.time, "sleep", lambda seconds: None)

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return setup.json.dumps(self.payload).encode()

    def run_with(*, models, toolsets):
        class Opener:
            def open(self, request, timeout):
                if isinstance(request, str):
                    return Response({"status": "ok"})
                if request.full_url.endswith("/models"):
                    return Response(models)
                if request.full_url.endswith("/capabilities"):
                    return Response(
                        {
                            "model": "share-corpus",
                            "features": {"cors": False},
                        }
                    )
                return Response(toolsets)

        monkeypatch.setattr(
            setup.urllib.request,
            "build_opener",
            lambda *handlers: Opener(),
        )
        setup._check_api(
            base_url="http://127.0.0.1:8643/v1",
            api_key="check-key",
            expected_model="share-corpus",
        )

    with pytest.raises(RuntimeError, match="health check failed"):
        run_with(
            models={"data": [{"id": "share-corpus"}, {"id": "other"}]},
            toolsets={"data": []},
        )
    with pytest.raises(RuntimeError, match="health check failed"):
        run_with(
            models={"data": [{"id": "share-corpus"}]},
            toolsets={},
        )
    with pytest.raises(RuntimeError, match="health check failed"):
        run_with(
            models={"data": [{"id": "share-corpus"}, {"id": "share-corpus"}]},
            toolsets={"data": []},
        )
    with pytest.raises(RuntimeError, match="health check failed"):
        run_with(
            models={"data": [{"id": "share-corpus"}]},
            toolsets={"data": [{"enabled": False}]},
        )


def test_redirect_handler_refuses_authenticated_redirects():
    setup = load_setup_module()
    handler = setup._RejectRedirects()

    assert (
        handler.redirect_request(
            req=None,
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="https://external.example/steal",
        )
        is None
    )
