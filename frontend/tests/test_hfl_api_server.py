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


def test_management_contract_matches_runtime_and_all_references_resolve():
    from hfl_api import app

    root = Path(__file__).resolve().parents[2]
    contract = yaml.safe_load((root / "apps/hfl_corpus/openapi.yaml").read_text(encoding="utf-8"))
    live = app.openapi()
    for path, operations in live["paths"].items():
        if path.startswith(("/api/hfl/actions", "/api/hfl/categories", "/api/hfl/pins", "/api/hfl/roles")):
            assert contract["paths"][path] == operations
            for operation in operations.values():
                assert operation["security"] == [{"HTTPBearer": []}]
    for name in ("CreateAction", "UpdateAction", "ActionSource", "SaveCategory", "UpdateCategory", "CreatePin", "UpdatePin", "RoleWrite", "AuditRequest"):
        assert contract["components"]["schemas"][name] == live["components"]["schemas"][name]

    def check_refs(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/"):
                target = contract
                for segment in ref[2:].split("/"):
                    target = target[segment.replace("~1", "/").replace("~0", "~")]
            for child in value.values():
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)

    check_refs(contract)


def test_entity_review_contract_matches_runtime():
    from hfl_api import app
    root = Path(__file__).resolve().parents[2]
    contract = yaml.safe_load((root / 'apps/hfl_corpus/openapi.yaml').read_text(encoding='utf-8'))
    live = app.openapi()
    for suffix in ('types', 'create', 'type/{identity}', 'merges/batch', 'matching', 'backfill',
                   'soul/{identity}', 'context/{identity}', 'resolutions/{entry_id}/{mention_id}/undo'):
        path = '/api/hfl/entities/' + suffix
        assert contract['paths'][path] == live['paths'][path]
    for name in ('TypeWrite', 'TypedProfile', 'KindWrite', 'BatchSubmit', 'MergeSubmit',
                 'SoulWrite', 'IdentityRule', 'Relationship', 'JournalEntry'):
        assert contract['components']['schemas'][name] == live['components']['schemas'][name]
