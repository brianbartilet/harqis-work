# Filesystem MCP Integration

Local file and directory operations exposed through the HARQIS MCP server.

## MCP tools

`fs_read_file`, `fs_write_file`, `fs_list_directory`, `fs_create_directory`,
`fs_delete`, `fs_copy`, `fs_move`, `fs_file_info`, and `fs_search_files` cover
the basic filesystem surface.

The active agent harness and host account define the reachable filesystem.
Callers must resolve exact targets before destructive operations, avoid broad
recursive paths, and preserve user-owned work. `overwrite` and `recursive`
arguments are explicit safety boundaries rather than defaults to bypass.

The tools are registered by `register_filesystem_tools()` in `mcp/server.py`.
No `apps_config.yaml` block, credentials, or network service is required.

## Validation

Use a temporary directory for create, copy, move, search, and delete smoke
tests. Never validate destructive behavior against a repository root or home
directory.
