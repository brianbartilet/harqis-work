from typing import List

from apps.justtcg.references.dto.game import DtoJusttcgGame
from apps.justtcg.references.web.base_api_service import BaseApiServiceJusttcg
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceJusttcgGames(BaseApiServiceJusttcg):
    """JustTCG ``/games`` endpoint — the catalogue of supported games."""

    def __init__(self, config, **kwargs):
        super(ApiServiceJusttcgGames, self).__init__(config, **kwargs)

    @deserialized(List[DtoJusttcgGame])
    def list_games(self) -> List[DtoJusttcgGame]:
        """Return all supported games with aggregate value / sealed-product stats.

        Each game's ``id`` is the slug used as the ``game`` filter on the
        /sets and /cards endpoints.
        """
        self.request.get().set_base_uri('games')
        return self.client.execute_request(self.request.build())
