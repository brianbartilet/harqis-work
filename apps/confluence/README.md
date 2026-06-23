# apps/confluence

Thin REST client for Confluence (Cloud **and** Server / Data Center). Built for
the knowledge-radar workflow — it reads pages so they can be chunked, embedded,
and cross-linked against Jira / GitHub / HFL — but it is a normal app and can be
used directly or via MCP.

## Config

`apps_config.yaml` → `CONFLUENCE:` block. Secrets resolve from the gitignored
`.env/apps.env` (this repo is public — never hard-code a domain or token):

| Env var | Cloud | Server / DC |
| --- | --- | --- |
| `CONFLUENCE_DOMAIN` | `acme.atlassian.net` | `wiki.acme.com` |
| `CONFLUENCE_EMAIL` | your Atlassian email (→ Basic auth) | leave empty (→ Bearer PAT) |
| `CONFLUENCE_API_TOKEN` | Atlassian API token | personal access token |

`context_path` in the config defaults to `/wiki` (Cloud). For a Server/DC
install that serves the API at the host root, set it to `''`.

`BaseApiServiceConfluence` rebuilds `base_url` at runtime as
`https://<domain><context_path>/rest/api/` and picks Basic vs Bearer the same
way `apps/jira` does — email present → Basic, absent → Bearer.

## Service layer

`references/web/api/content.py` — `ApiServiceConfluenceContent`:

| Method | Endpoint | Use |
| --- | --- | --- |
| `search_cql(cql, limit, start, expand)` | `GET /content/search` | find pages by CQL |
| `get_page(page_id, expand)` | `GET /content/{id}` | full body + version + labels |
| `get_descendants(page_id, limit, start)` | `GET /content/{id}/descendant/page` | ingest a subtree |
| `list_spaces(limit, start, space_type)` | `GET /space` | discover spaces |
| `get_labels(page_id)` | `GET /content/{id}/label` | topic tags |

Page bodies come back as Confluence **storage format** (XHTML);
`workflows/knowledge/chunking.py:strip_confluence_storage()` flattens them to
plain text for embedding.

## MCP

`mcp.py` exposes `confluence_search`, `confluence_get_page`,
`confluence_list_spaces` (registered as **"Confluence"** in `mcp/server.py`).

## Quick check

```bash
python -c "from apps.confluence.config import CONFIG; \
           from apps.confluence.references.web.api.content import ApiServiceConfluenceContent; \
           print(ApiServiceConfluenceContent(CONFIG).list_spaces(limit=5))"
```

(Bootstrap env first — see the `harqis-env-context` skill — or the `${...}`
placeholders won't resolve.)
