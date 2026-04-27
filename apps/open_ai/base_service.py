# DEPRECATED: BaseServiceHarqisGPT and the services under references/services/assistants/
# use the OpenAI Assistants v2 REST fixtures (OpenAI-Beta: assistants=v2 header).
# The Assistants API is legacy — OpenAI now recommends the Responses API for new work.
#
# Migration path:
#   - Text generation   → apps.open_ai.references.web.api.responses.ApiServiceOpenAiResponses
#   - Code execution    → apps.open_ai.references.web.api.code_interpreter.ApiServiceOpenAiCodeInterpreter
#   - Config key        → OPEN_AI (was HARQIS_GPT) in apps_config.yaml
#
# This file is kept to avoid breaking existing workflows (hud desktop log analysis,
# assistant_id_desktop, assistant_id_reporter). Do not use for new integrations.

import warnings

from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders
from openai import OpenAI


class BaseServiceHarqisGPT(BaseFixtureServiceRest):
    """DEPRECATED — use BaseApiServiceOpenAi in references/web/base_api_service.py instead."""

    def __init__(self, config, **kwargs):
        warnings.warn(
            "BaseServiceHarqisGPT is deprecated. Use ApiServiceOpenAiResponses "
            "or ApiServiceOpenAiCodeInterpreter from references/web/api/ instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super(BaseServiceHarqisGPT, self).__init__(config, **kwargs)
        api_key = self.config.app_data["api_key"]
        self.request\
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {api_key}')

        self.native_client = OpenAI(api_key=api_key)

