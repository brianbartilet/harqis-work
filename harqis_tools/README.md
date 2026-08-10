# harqis-tools CLI

`harqis_tools` is the low-context, JSON-first command surface for every app in
`harqis-work`. It reuses the existing MCP registrations, but imports only the app
selected by a command. Existing MCP clients remain fully compatible.

```powershell
# Discover apps without importing any app modules
python -m harqis_tools apps

# Import one app and discover its operations
python -m harqis_tools commands scryfall
python -m harqis_tools schema trello create_trello_card

# Invoke a read operation
python -m harqis_tools call scryfall get_scryfall_card_prices `
  --input '{"identifier":"Black Lotus"}'

# Writes require explicit confirmation
python -m harqis_tools call trello create_trello_card `
  --input '{"list_id":"...","name":"Review CLI migration"}' `
  --confirm-write
```

All commands emit an envelope shaped as `{"ok": true, "result": ...}` on stdout.
Validation and execution failures emit `{"ok": false, "error": ...}` on stderr and
return a non-zero status. Pass `--input -` to read a JSON object from stdin.

For Kanban-equivalent authorization, pass `--profile <profile.yaml>`. The selected
app must appear in `tools.mcp_apps`; native `tools.allowed` remains independent.
Every call is recorded through the existing `AuditLogger`, defaulting to
`logs/harqis_cli_audit.jsonl`. Override this with `HARQIS_CLI_AUDIT_LOG`.

## Architecture

`catalog.py` is the canonical app registry. It stores import strings rather than
imported callables, so discovery is cheap and side-effect free. The CLI, standalone
MCP server, and Kanban MCP bridge all consume this catalog. App implementations and
MCP tool names remain in `apps/<app>/mcp.py`.

Adding a catalog entry exposes an app through all three surfaces. Use
`/create-new-mcp <app>` to audit the service layer, create its compatible MCP adapter,
and register the app in this shared catalog.
