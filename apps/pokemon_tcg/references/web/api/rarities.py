from typing import List

from apps.pokemon_tcg.references.web.base_api_service import BaseApiServicePokemonTcg


class ApiServicePokemonTcgRarities(BaseApiServicePokemonTcg):
    """Pokemon TCG API ``/rarities`` endpoint — the canonical rarity strings.

    The API has no 'Full Art' rarity: full arts surface as 'Rare Ultra' /
    'Ultra Rare' / 'Rare Holo V' etc., so any rarity filter must be built from
    the exact strings this endpoint returns.
    """

    def __init__(self, config, **kwargs):
        super(ApiServicePokemonTcgRarities, self).__init__(config, **kwargs)

    def list_rarities(self) -> List[str]:
        """Return every rarity string known to the API (plain strings, so the
        DTO deserializer is bypassed and the ``data`` envelope unwrapped here)."""
        self.request.get().set_base_uri('rarities')
        response = self.client.execute_request(self.request.build())
        data = getattr(response, 'data', response)
        if isinstance(data, dict) and isinstance(data.get('data'), list):
            return list(data['data'])
        return list(data) if isinstance(data, list) else []
