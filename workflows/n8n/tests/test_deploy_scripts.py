from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_DIR = REPO_ROOT / "workflows" / "n8n" / "deploy"
SCRIPT_NAMES = ("backup", "deploy", "restore")


def _read_script(stem: str, suffix: str) -> str:
    return (DEPLOY_DIR / f"{stem}.{suffix}").read_text(encoding="utf-8")


def test_unix_deploy_scripts_target_compose_bind_data_dir():
    for stem in SCRIPT_NAMES:
        content = _read_script(stem, "sh")

        assert "N8N_DATA_DIR" in content
        assert "HARQIS_DATA_ROOT" in content
        assert "harqis-work_n8n_data" not in content
        assert "docker volume" not in content
        assert ":/home/node/.n8n" in content or ":/data" in content


def test_windows_deploy_scripts_target_compose_bind_data_dir():
    for stem in SCRIPT_NAMES:
        content = _read_script(stem, "bat")

        assert "N8N_DATA_DIR" in content
        assert "HARQIS_DATA_ROOT" in content
        assert "harqis-work_n8n_data" not in content
        assert "docker volume" not in content.lower()
        assert ":/home/node/.n8n" in content or ":/data" in content


def test_n8n_readme_documents_bind_mount_not_stale_api_key():
    readme = (REPO_ROOT / "workflows" / "n8n" / "README.md").read_text(encoding="utf-8")

    assert "${HARQIS_DATA_ROOT:-./.harqis-data}/n8n" in readme
    assert "N8N_API_KEY" not in readme
    assert "Docker CLI import" in readme
