# Grok Integration

xAI REST integration for chat completion, web search, X search, model listing,
and embeddings.

## Setup

Set `GROK_API_KEY` in `.env/apps.env`. The `GROK` block in `apps_config.yaml`
targets `https://api.x.ai/v1` and defaults to model `grok-3`.

## MCP tools

`grok_chat`, `grok_web_search`, `grok_x_search`, `grok_list_models`, and
`grok_embed` are registered by `register_grok_tools()` in `mcp/server.py`.
Service implementations live under `references/web/api/`.

## Testing

```powershell
pytest apps/grok/tests
```

Tests call the live xAI API and can consume paid quota. Search results and the
available model list are upstream-dependent.
