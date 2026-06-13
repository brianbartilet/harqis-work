from typing import List, Optional

from apps.pokemon_tcg.references.dto.set import DtoPokemonTcgSet
from apps.pokemon_tcg.references.web.base_api_service import BaseApiServicePokemonTcg
from core.web.services.core.decorators.deserializer import deserialized


class ApiServicePokemonTcgSets(BaseApiServicePokemonTcg):
    """Pokemon TCG API ``/sets`` endpoint — expansion set catalogue."""

    def __init__(self, config, **kwargs):
        super(ApiServicePokemonTcgSets, self).__init__(config, **kwargs)

    @deserialized(List[DtoPokemonTcgSet])
    def list_sets(self,
                  q: Optional[str] = None,
                  page: Optional[int] = None,
                  page_size: Optional[int] = None,
                  order_by: Optional[str] = None) -> List[DtoPokemonTcgSet]:
        """List sets, optionally filtered with the Lucene-like query syntax.

        Args:
            q:         Query string, e.g. 'series:"Scarlet & Violet"'.
            page:      1-based page number.
            page_size: Results per page.
            order_by:  Sort field(s), e.g. '-releaseDate'.
        """
        self.request.get().set_base_uri('sets')
        params = {'q': q, 'page': page, 'pageSize': page_size, 'orderBy': order_by}
        for key, value in params.items():
            if value is not None:
                self.request.add_query_string(key, value)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoPokemonTcgSet, child='data')
    def get_set(self, set_id: str) -> DtoPokemonTcgSet:
        """Return a single set by id (e.g. 'sv3pt5')."""
        self.request.get().set_base_uri(f'sets/{set_id}')
        return self.client.execute_request(self.request.build())
