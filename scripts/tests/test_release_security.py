"""Exercise rendered Compose bindings without starting containers or using secrets."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def render_compose(tmp_path, **overrides):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker CLI is required to render Compose")
    root = Path(__file__).resolve().parents[2]
    env_file = tmp_path / ".env" / "apps.env"
    env_file.parent.mkdir()
    env_file.write_text("", encoding="utf-8")
    # Do not inherit provider credentials or operator bind-address overrides.
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE",
                            "TEMP", "TMP", "DOCKER_CONFIG", "APPDATA", "LOCALAPPDATA",
                            "PROGRAMDATA", "PROGRAMFILES", "PATHEXT"}}
    env.update(overrides)
    result = subprocess.run(
        [docker, "compose", "--env-file", str(env_file),
         "--project-directory", str(tmp_path), "-f", str(root / "docker-compose.yml"),
         "config", "--format", "json"],
        env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]


def test_default_published_ports_are_host_only(tmp_path):
    services = render_compose(tmp_path)
    ports = [p for service in services.values() for p in service.get("ports", [])]
    assert ports
    assert all(p["host_ip"] == "127.0.0.1" for p in ports)
    # Internal clients keep their service-name connectivity after hardening.
    assert services["recorder"]["environment"]["OTR_HOST"] == "mosquitto"
    assert services["kibana"]["environment"]["ELASTICSEARCH_HOSTS"] == "http://elasticsearch:9200"


def test_private_binding_override_is_scoped_to_one_service(tmp_path):
    services = render_compose(tmp_path, REDIS_BIND_ADDRESS="192.0.2.10", REDIS_PORT="16379")
    assert services["redis"]["ports"][0]["host_ip"] == "192.0.2.10"
    assert str(services["redis"]["ports"][0]["published"]) == "16379"
    assert all(p["host_ip"] == "127.0.0.1"
               for name, service in services.items() if name != "redis"
               for p in service.get("ports", []))
