#!/bin/bash
# Close terminal windows with "Process completed" message (post-deploy cleanup, macOS)
# Usage: bash scripts/close-completed-windows.sh

PATTERN="${1:-Process completed}"

echo "Searching for Terminal windows containing '$PATTERN'..."

osascript - "$PATTERN" <<'APPLESCRIPT'
on run argv
    set search_pattern to item 1 of argv
    set found_count to 0

    tell application "Terminal"
        repeat with w in windows
            set window_title to name of w

            if window_title contains search_pattern then
                try
                    close w
                    log "Found and closed: " & window_title
                    set found_count to found_count + 1
                on error err
                    log "Could not close window: " & err
                end try
            end if
        end repeat
    end tell

    if found_count is 0 then
        log "No Terminal windows matching '" & search_pattern & "' found."
    else
        log "Closed " & found_count & " window(s)."
    end if
end run
APPLESCRIPT

echo "Cleanup complete."
