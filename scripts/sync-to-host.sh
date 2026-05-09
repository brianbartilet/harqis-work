#!/usr/bin/env bash
# Push a configured set of files to a remote harqis-work checkout via tar | ssh.
# One password prompt: bundles everything into a single tar stream piped over ssh.
#
# All identifying info (machine keys, hosts, paths, file list) lives in
# machines.local.toml (gitignored). This script ships no defaults of its own.
#
# Required toml shape:
#   [sync]
#   default_machine = "<machine-key>"             # used when MACHINE_KEY is unset
#   items           = ["<path>", "<path>", ...]   # repo-relative paths to push
#
#   [ssh.<machine-key>]
#   user = "<remote-user>"
#   host = "<reachable-hostname>"
#   path = "<remote-destination>"
#
# Usage:
#   ./scripts/sync-to-host.sh
#   MACHINE_KEY=<key> ./scripts/sync-to-host.sh
#   SSH_TARGET=user@host REMOTE_PATH='~/elsewhere' ./scripts/sync-to-host.sh   # explicit override
#   ./scripts/sync-to-host.sh --list
#   ./scripts/sync-to-host.sh --dry-run

set -euo pipefail

MACHINE_KEY="${MACHINE_KEY:-}"
SSH_TARGET="${SSH_TARGET:-}"
REMOTE_PATH="${REMOTE_PATH:-}"
DRY_RUN=0
LIST=0

for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN=1 ;;
        --list|-l)    LIST=1 ;;
        --help|-h)
            sed -n '2,21p' "$0"
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname -- "$script_dir")"
cd "$repo_root"

toml_path="$repo_root/machines.local.toml"
if [ ! -f "$toml_path" ]; then
    echo "machines.local.toml not found at $toml_path. Create it with [sync] and [ssh.*] blocks (see script header)." >&2
    exit 1
fi

# Extract the body of [<header>] (lines until the next [section] header).
section_body() {
    awk -v sect="[$1]" '
        $0 == sect { in_sect=1; next }
        /^\[/      { in_sect=0 }
        in_sect    { print }
    ' "$toml_path"
}

field() {
    # field <body> <name> → first matching string value; empty if missing
    echo "$1" | sed -nE "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*\"([^\"]+)\".*/\1/p" | head -n1
}

array_field() {
    # array_field <body> <name> → newline-separated string values
    local body="$1" name="$2"
    echo "$body" \
        | awk -v name="$name" '
            BEGIN { in_arr=0 }
            {
                if (!in_arr && $0 ~ "^[[:space:]]*"name"[[:space:]]*=[[:space:]]*\\[") {
                    in_arr=1
                    sub("^[^[]*\\[", "")
                }
                if (in_arr) {
                    buf = buf $0 " "
                    if ($0 ~ "\\]") { in_arr=0; sub("\\].*", "", buf); print buf; buf="" }
                }
            }
        ' \
        | grep -oE '"[^"]+"' \
        | sed -E 's/^"|"$//g'
}

if [ "$LIST" -eq 1 ]; then
    echo "Configured [ssh.*] targets in machines.local.toml:"
    keys=$(grep -oE '^\[ssh\.[^]]+\]' "$toml_path" | sed -E 's/^\[ssh\.|\]$//g')
    if [ -z "$keys" ]; then echo "  (none)"; exit 0; fi
    while IFS= read -r key; do
        body="$(section_body "ssh.$key")"
        u="$(field "$body" user)"
        h="$(field "$body" host)"
        p="$(field "$body" path)"
        printf "  - %-24s %s@%s:%s\n" "$key" "$u" "$h" "$p"
    done <<< "$keys"
    exit 0
fi

sync_body="$(section_body sync)"
if [ -z "$sync_body" ]; then
    echo "[sync] section missing from machines.local.toml. Add 'default_machine' and 'items' (see script header)." >&2
    exit 1
fi

if [ -z "$MACHINE_KEY" ]; then
    MACHINE_KEY="$(field "$sync_body" default_machine)"
    if [ -z "$MACHINE_KEY" ]; then
        echo "[sync] default_machine is not set; set MACHINE_KEY=<key> or add it to machines.local.toml." >&2
        exit 1
    fi
fi

mapfile -t items < <(array_field "$sync_body" items)
if [ "${#items[@]}" -eq 0 ]; then
    echo "[sync] items is empty or missing; populate it in machines.local.toml." >&2
    exit 1
fi

ssh_body="$(section_body "ssh.$MACHINE_KEY")"
if [ -z "$ssh_body" ]; then
    echo "[ssh.$MACHINE_KEY] not found in machines.local.toml. Run with --list to see configured targets." >&2
    exit 1
fi

if [ -z "$SSH_TARGET" ]; then
    u="$(field "$ssh_body" user)"
    h="$(field "$ssh_body" host)"
    if [ -z "$u" ] || [ -z "$h" ]; then
        echo "[ssh.$MACHINE_KEY] is missing 'user' or 'host'." >&2
        exit 1
    fi
    SSH_TARGET="${u}@${h}"
fi
if [ -z "$REMOTE_PATH" ]; then
    REMOTE_PATH="$(field "$ssh_body" path)"
    if [ -z "$REMOTE_PATH" ]; then
        echo "[ssh.$MACHINE_KEY] is missing 'path' (and no REMOTE_PATH given)." >&2
        exit 1
    fi
fi

for item in "${items[@]}"; do
    if [ ! -e "$item" ]; then
        echo "Missing source: $item (cwd=$repo_root)" >&2
        exit 1
    fi
done

echo "Source repo : $repo_root"
echo "Machine key : $MACHINE_KEY"
echo "SSH target  : $SSH_TARGET"
echo "Remote path : $REMOTE_PATH"
echo "Items       :"
for item in "${items[@]}"; do echo "  - $item"; done

remote_cmd="mkdir -p $REMOTE_PATH && tar -xf - -C $REMOTE_PATH"

if [ "$DRY_RUN" -eq 1 ]; then
    echo
    echo "[dry-run] Would run:"
    echo "  tar -cf - ${items[*]} | ssh $SSH_TARGET \"$remote_cmd\""
    exit 0
fi

echo
echo "Streaming archive to $SSH_TARGET ..."
tar -cf - "${items[@]}" | ssh "$SSH_TARGET" "$remote_cmd"

echo
echo "Done."
