from typing import List, Optional

from apps.justtcg.references.dto.set import DtoJusttcgSet
from apps.justtcg.references.web.base_api_service import BaseApiServiceJusttcg
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceJusttcgSets(BaseApiServiceJusttcg):
    """JustTCG ``/sets`` endpoint — sets within a game."""

    def __init__(self, config, **kwargs):
        super(ApiServiceJusttcgSets, self).__init__(config, **kwargs)

    @deserialized(List[DtoJusttcgSet])
    def list_sets(self,
                  game: Optional[str] = None,
                  q: Optional[str] = None,
                  limit: Optional[int] = None,
                  offset: Optional[int] = None) -> List[DtoJusttcgSet]:
        """List sets, optionally filtered by game and/or name search.

        Args:
            game:   Restrict to a single game id (e.g. 'pokemon', 'mtg').
            q:      Search sets by name.
            limit:  Page size.
            offset: Pagination offset.
        """
        self.request.get().set_base_uri('sets')
        if game:
            self.request.add_query_string('game', game)
        if q:
            self.request.add_query_string('q', q)
        if limit is not None:
            self.request.add_query_string('limit', limit)
        if offset is not None:
            self.request.add_query_string('offset', offset)
        return self.client.execute_request(self.request.build())
