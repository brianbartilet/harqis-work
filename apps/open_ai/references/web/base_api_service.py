from openai import OpenAI
from core.web.services.fixtures.rest import BaseFixtureServiceRest


class BaseApiServiceOpenAi(BaseFixtureServiceRest):
    """Base service for the OpenAI SDK integration.

    Wraps BaseFixtureServiceRest for config/auth and exposes self.native_client
    (the official openai.OpenAI SDK client) for all API calls.
    """

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        api_key = config.app_data["api_key"]
        self.native_client = OpenAI(api_key=api_key)
        self.default_model: str = config.app_data.get("model", "gpt-4.1")
