"""Bounded canonical PR intake command; credentials remain at the owner API."""
from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflGithubUpdates(ApiServiceHflCorpusExtended):
    def sync_github_updates(self, pages: int = 5, limit: int = 10, run_id: str = '') -> dict:
        """Create/reconcile review entries, actions and links for owner-connected PRs.

        Pages must be 1–10 and limit 1–25. Repeated calls resume durable progress.
        This writes canonical data and can complete/dismiss PR-linked actions.
        """
        if type(pages) is not int or not 1 <= pages <= 10 or type(limit) is not int or not 1 <= limit <= 25:
            raise ValueError('Use pages 1–10 and limit 1–25.')
        response = self._raw_request('POST', 'github-updates/sync',
            json={'pages': pages, 'limit': limit, 'run_id': run_id}, timeout=900)
        if response.is_redirect:
            raise ValueError('Unexpected canonical API redirect.')
        return response.json()
