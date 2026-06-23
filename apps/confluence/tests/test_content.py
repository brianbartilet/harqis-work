"""
apps/confluence — service tests.

Two layers:
  * Pure-logic tests (no network/creds) for the custom base_url + auth-mode
    selection in BaseApiServiceConfluence. These always run.
  * Live smoke tests that hit the configured Confluence and skip cleanly when
    no domain is configured (same convention as apps/jira tests).
"""

import pytest
from hamcrest import assert_that, equal_to, instance_of

from core.web.services.core.config.webservice import AppConfigWSClient
from apps.confluence.config import CONFIG
from apps.confluence.references.web.api.content import ApiServiceConfluenceContent


def _cfg(domain, *, api_token="tok", email=None, context_path="/wiki"):
    app_data = {"domain": domain, "api_token": api_token, "context_path": context_path}
    if email is not None:
        app_data["email"] = email
    return AppConfigWSClient(
        app_id="confluence",
        client="rest",
        parameters={
            "base_url": "https://placeholder/wiki/rest/api/",
            "response_encoding": "utf-8",
            "verify": True,
            "timeout": 60,
            "stream": True,
        },
        app_data=app_data,
        return_data_only=True,
    )


def _has_live_config() -> bool:
    try:
        domain = CONFIG.app_data.get("domain") or ""
    except Exception:
        return False
    return bool(domain.strip()) and "placeholder" not in domain


# --------------------------- pure-logic tests --------------------------- #

def test_cloud_base_url_uses_wiki_context():
    svc = ApiServiceConfluenceContent(_cfg("acme.atlassian.net", email="me@acme.com"))
    assert_that(svc.client.base_url, equal_to("https://acme.atlassian.net/wiki/rest/api/"))


def test_server_empty_context_path_serves_at_root():
    svc = ApiServiceConfluenceContent(_cfg("wiki.acme.com", email=None, context_path=""))
    assert_that(svc.client.base_url, equal_to("https://wiki.acme.com/rest/api/"))


def test_context_path_is_normalised():
    # Leading/trailing slashes and bare names both normalise to "/name".
    svc = ApiServiceConfluenceContent(_cfg("acme.atlassian.net", email="me@acme.com",
                                           context_path="confluence/"))
    assert_that(svc.client.base_url, equal_to("https://acme.atlassian.net/confluence/rest/api/"))


# ----------------------------- live smoke ------------------------------ #

@pytest.mark.smoke
def test_list_spaces_live():
    if not _has_live_config():
        pytest.skip("CONFLUENCE_DOMAIN not configured")
    result = ApiServiceConfluenceContent(CONFIG).list_spaces(limit=5)
    assert_that(result, instance_of(dict))
    assert_that(result.get("results"), instance_of(list))
