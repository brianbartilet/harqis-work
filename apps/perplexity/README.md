# Perplexity AI

Perplexity AI integration — Sonar chat with built-in live web search, direct
search API, embeddings, and async deep research.

- **API docs:** https://docs.perplexity.ai/
- **Auth:** Bearer token (`Authorization: Bearer $PERPLEXITY_API_KEY`)
- **Base URL:** `https://api.perplexity.ai`

## Supported Automations

- [x] **webservices** — REST API client over httpx + OpenAI-compatible chat
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] iot

## Directory Structure

```
apps/perplexity/
├── __init__.py
├── config.py                       # loads PERPLEXITY section from apps_config.yaml
├── mcp.py                          # registers MCP tools
├── README.md
├── references/
│   ├── dto/
│   │   ├── chat.py                 # DtoPerplexityChatResponse, Choice, Message, Usage
│   │   ├── search.py               # DtoPerplexitySearchResponse, SearchResult
│   │   ├── embeddings.py           # DtoPerplexityEmbedding(Response/Usage)
│   │   └── models.py               # DtoPerplexityModel
│   └── web/
│       ├── base_api_service.py     # OpenAI SDK + httpx Bearer auth
│       └── api/
│           ├── chat.py             # /chat/completions + /async/chat/completions
│           ├── search.py           # /search
│           ├── embeddings.py       # /embeddings + /embeddings/contextualized
│           └── models.py           # /models
└── tests/
    └── test_chat.py                # all skipped until API key is set
```

## Configuration

`apps_config.yaml`:
```yaml
PERPLEXITY:
  app_id: 'perplexity'
  client: 'rest'
  parameters:
    base_url: 'https://api.perplexity.ai'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    api_key: ${PERPLEXITY_API_KEY}
    model: 'sonar'
  return_data_only: True
```

`.env/apps.env`:
```
PERPLEXITY_API_KEY=<your key from https://www.perplexity.ai/settings/api>
```

## Available Services

| Service class | Methods | Purpose |
|---|---|---|
| `ApiServicePerplexityChat` | `chat`, `complete`, `submit_async`, `get_async`, `list_async` | Sonar chat completions with web search + async deep research |
| `ApiServicePerplexitySearch` | `search` | Direct web search returning ranked URLs |
| `ApiServicePerplexityEmbeddings` | `embed`, `embed_contextualized` | Generate embedding vectors |
| `ApiServicePerplexityModels` | `list_models` | List available models |

## MCP Tools

| Tool | Args | Returns |
|---|---|---|
| `perplexity_chat` | `prompt`, `model`, `system?`, `temperature?`, `max_tokens?`, `search_domain_filter?`, `search_recency_filter?` | `{id, model, output_text, citations, finish_reason, usage}` |
| `perplexity_submit_async` | `prompt`, `model`, `system?`, `max_tokens?` | Async request envelope with `id` |
| `perplexity_get_async` | `request_id` | Async result (status + completion if ready) |
| `perplexity_list_async` | — | List of all async requests |
| `perplexity_search` | `query`, `max_results?`, `search_domain_filter?`, `search_recency_filter?`, `language?` | `{query, results, count}` |
| `perplexity_embed` | `text`, `model?` | `{model, embedding_dims, embedding, usage}` |
| `perplexity_list_models` | — | List of model dicts |

## Tests

All tests are currently `@pytest.mark.skip`-ed — Perplexity API access is not
yet provisioned for this account. Once you set `PERPLEXITY_API_KEY` in
`.env/apps.env`, remove the `@pytest.mark.skip` decorators from
`apps/perplexity/tests/test_chat.py` to enable them.

```sh
pytest apps/perplexity/tests/ -m smoke
pytest apps/perplexity/tests/ -m sanity
```

## Notes

- **Models:** `sonar` (default, fast), `sonar-pro` (better quality), `sonar-reasoning` (chain-of-thought),
  `sonar-deep-research` (long-running research, best used via `submit_async`).
- **Citations:** Sonar always returns a `citations` array of source URLs alongside the response text.
- **Search filters:** `search_domain_filter` accepts a whitelist (e.g. `['nytimes.com', 'wikipedia.org']`)
  or blacklist (prefix domain with `-`, e.g. `'-pinterest.com'`).
- **Recency filters:** `search_recency_filter` accepts `'month'`, `'week'`, `'day'`, or `'hour'`.
- **OpenAI compatibility:** `/chat/completions` is OpenAI-compatible — the `BaseApiServicePerplexity`
  exposes `self.native_client` (an `OpenAI` SDK instance) for streaming or tool-use scenarios that need it.
- **Rate limits:** see https://docs.perplexity.ai/docs/rate-limits — typically generous on Sonar
  but `sonar-deep-research` has a much lower per-minute cap; use the async API for that model.
