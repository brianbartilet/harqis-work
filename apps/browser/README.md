# Browser MCP Integration

Lightweight HTTP fetching and HTML extraction exposed through the HARQIS MCP
server. This integration is for deterministic page reads; use `apps/playwright`
when a page requires JavaScript or interaction.

## MCP tools

| Tool | Purpose |
|---|---|
| `browser_fetch` | Issue a guarded HTTP request and return status, headers, and body. |
| `browser_get_text` | Fetch HTML and extract readable text. |
| `browser_get_links` | Extract page links, optionally restricted to the source domain. |
| `browser_extract_json` | Fetch and decode JSON. |
| `browser_get_headers` | Fetch response headers. |

Private, loopback, link-local, and otherwise non-public destinations are
rejected to reduce SSRF risk, including across redirects. Set
`BROWSER_MCP_ALLOW_PRIVATE=1` only in a trusted environment when private-network
access is intentional.

The tools are registered by `register_browser_tools()` in `mcp/server.py`. No
`apps_config.yaml` block or credentials are required.

## Validation

Run MCP registration tests or exercise the tools against a known public URL.
Network responses are live and may change independently of this repository.
