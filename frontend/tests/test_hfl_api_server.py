from pathlib import Path

import yaml


def test_standalone_hfl_api_exposes_swagger_and_corpus_routes():
    from hfl_api import app

    paths = app.openapi()["paths"]
    assert "/health" in paths
    assert "/api/hfl/entries" in paths
    assert "/api/hfl/documents" in paths
    assert app.docs_url == "/docs"
    assert app.openapi_url == "/openapi.json"


def test_checked_in_openapi_paths_match_the_live_server():
    from hfl_api import app

    root = Path(__file__).resolve().parents[2]
    checked_in = yaml.safe_load(
        (root / "apps" / "hfl_corpus" / "openapi.yaml").read_text(encoding="utf-8")
    )
    assert set(checked_in["paths"]) == set(app.openapi()["paths"])


def test_standalone_openapi_declares_bearer_authentication():
    from hfl_api import app

    schema = app.openapi()
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert schema["paths"]["/api/hfl/entries"]["post"]["security"] == [
        {"HTTPBearer": []}
    ]
