from openai import OpenAI
from core.web.services.fixtures.rest import BaseFixtureServiceRest

DEFAULT_MODEL = "grok-3"
EMBEDDING_MODEL = "grok-3-embedding-exp"


class BaseApiServiceGrok(BaseFixtureServiceRest):
    """Base service for xAI Grok via the OpenAI-compatible SDK.

    Uses the official openai SDK pointed at https://api.x.ai/v1.
    self.native_client is an openai.OpenAI instance ready to use.
    """

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.native_client = OpenAI(
            api_key=config.app_data["api_key"],
            base_url="https://api.x.ai/v1",
        )
        self.default_model: str = config.app_data.get("model", DEFAULT_MODEL)
