#!/usr/bin/env sh
# Cross-platform launcher for Claude Code's project hook shell.
set -eu

hfl_root=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}
if [ -x "$hfl_root/.venv/bin/python" ]; then
  hfl_python="$hfl_root/.venv/bin/python"
elif [ -f "$hfl_root/.venv/Scripts/python.exe" ]; then
  hfl_python="$hfl_root/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  hfl_python=python3
else
  hfl_python=python
fi

hfl_script="$hfl_root/scripts/agents/hfl/capture_session_event.py"
case "$hfl_python" in
  *.exe)
    if command -v cygpath >/dev/null 2>&1; then
      hfl_script=$(cygpath -w "$hfl_script")
    elif command -v wslpath >/dev/null 2>&1; then
      hfl_script=$(wslpath -w "$hfl_script")
    fi
    ;;
esac

exec "$hfl_python" "$hfl_script" \
  --surface claude-code --hook
