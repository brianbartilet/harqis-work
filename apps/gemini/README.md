# gemini — Google Gemini API

## Description

Integration with the [Google Gemini REST API (v1beta)](https://ai.google.dev/api/rest).
Covers model discovery, text generation, token counting, and vector embeddings.

**Base URL:** `https://generativelanguage.googleapis.com/v1beta/`
**Auth:** API key passed as query parameter `?key=<GEMINI_API_KEY>` on every request.
**API Docs:** https://ai.google.dev/api/rest

---

## Supported Automations

- [x] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] iot

---

## Directory Structure

```
apps/gemini/
├── __init__.py
├── config.py
├── mcp.py
├── references/
│   ├── __init__.py
│   ├── dto/
│   │   ├── __init__.py
│   │   ├── models.py          # DtoGeminiModel, DtoGeminiContent, DtoGeminiCandidate, …
│   │   └── embed.py           # DtoGeminiEmbedding, DtoGeminiEmbedContentResponse, …
│   └── web/
│       ├── __init__.py
│       ├── base_api_service.py
│       └── api/
│           ├── __init__.py
│           ├── models.py      # ApiServiceGeminiModels
│           ├── generate.py    # ApiServiceGeminiGenerate
│           └── embed.py       # ApiServiceGeminiEmbed
└── tests/
    ├── __init__.py
    ├── test_models.py
    ├── test_generate.py
    └── test_embed.py
```

---

## Configuration

### `apps_config.yaml` snippet

```yaml
GEMINI:
  app_id: gemini
  client:
    base_url: https://generativelanguage.googleapis.com/v1beta/
    verify_ssl: true
  parameters: {}
  app_data:
    api_key: ${GEMINI_API_KEY}
  return_data_only: true
```

### Required environment variables (`.env/apps.env`)

```env
GEMINI_API_KEY=
```

Obtain an API key from the [Google AI Studio](https://aistudio.google.com/app/apikey).

---

## Available Services

| Service class | Method | Description |
|---|---|---|
| `ApiServiceGeminiModels` | `list_models(page_size)` | List all models available to the API key |
| `ApiServiceGeminiModels` | `get_model(model_name)` | Get metadata for a specific model |
| `ApiServiceGeminiGenerate` | `generate_content(prompt, model, temperature, max_output_tokens, top_p, top_k, system_instruction)` | Generate text from a prompt |
| `ApiServiceGeminiGenerate` | `count_tokens(prompt, model)` | Count tokens without generating |
| `ApiServiceGeminiEmbed` | `embed_content(text, model, task_type, title)` | Generate a single text embedding |
| `ApiServiceGeminiEmbed` | `batch_embed_contents(texts, model, task_type)` | Batch generate text embeddings |

---

## MCP Tools

| Tool | Args | Returns |
|---|---|---|
| `list_gemini_models` | `page_size?` | List of model dicts (name, displayName, supportedGenerationMethods, …) |
| `get_gemini_model` | `model_name` | Single model metadata dict |
| `gemini_generate_content` | `prompt`, `model?`, `temperature?`, `max_output_tokens?`, `system_instruction?` | Dict with candidates list and usage metadata |
| `gemini_count_tokens` | `prompt`, `model?` | Dict with `total_tokens` count |
| `gemini_embed_content` | `text`, `model?`, `task_type?` | Dict with `embedding.values` float list |
| `gemini_batch_embed_contents` | `texts`, `model?`, `task_type?` | Dict with `embeddings` list |

---

## Tests

```sh
# Smoke tests (fast, read-only)
pytest apps/gemini/tests/ -m smoke

# Full suite
pytest apps/gemini/tests/
```

Requires `GEMINI_API_KEY` set in `.env/apps.env`.

---

## Notes

- **Default generation model:** `models/gemini-2.0-flash` (fast, cost-efficient).
- **Default embedding model:** `models/text-embedding-004` (768-dimensional output).
- **Rate limits:** Free tier is 15 RPM / 1 500 RPD for Gemini 2.0 Flash. Use `count_tokens` before large batches.
- **task_type values for embeddings:** `RETRIEVAL_DOCUMENT`, `RETRIEVAL_QUERY`, `SEMANTIC_SIMILARITY`, `CLASSIFICATION`, `CLUSTERING`.
- The API key is appended automatically to every request via `session.params` — no per-method changes needed.
