# Playwright MCP Integration

Headless browser automation for pages that require JavaScript, selectors, or
interaction. Prefer `apps/browser` for simple HTTP fetches.

## MCP tools

| Tool | Purpose |
|---|---|
| `playwright_screenshot` | Capture a rendered page screenshot. |
| `playwright_get_text` | Read rendered text from a page or selector. |
| `playwright_click_and_get_text` | Click an element and read the resulting text. |
| `playwright_fill_and_submit` | Fill form fields and submit. |
| `playwright_evaluate` | Evaluate JavaScript in the page context. |

The tools are registered by `register_playwright_tools()` in `mcp/server.py`.
No `apps_config.yaml` block is required, but the Python Playwright package and a
compatible browser binary must be installed on the MCP host.

Browser actions may trigger real external side effects. Confirm form targets
and submitted values before using mutating interactions.
