#!/bin/bash
# Close idle/unused Terminal windows (post-deploy cleanup, macOS)
# Usage: bash scripts/close-completed-windows.sh
# Closes: idle -zsh shells + completed harqis-work windows (no active processes)

osascript <<'APPLESCRIPT'
tell application "Terminal"
    set windows_to_close to {}

    -- Collect windows to close (don't close during iteration)
    repeat with w in windows
        set window_title to name of w

        -- Mark idle -zsh shells
        if window_title ends with "— -zsh — 120×30" then
            set end of windows_to_close to {w, "idle"}
        end if

        -- Mark completed harqis-work windows
        if (window_title contains "harqis-work:scheduler" or window_title contains "harqis-work:worker") and not (window_title contains "Python" or window_title contains "celery") then
            set end of windows_to_close to {w, "completed"}
        end if
    end repeat

    -- Now close them
    set idle_count to 0
    set completed_count to 0
    repeat with window_item in windows_to_close
        set w to window_item's item 1
        set reason to window_item's item 2
        try
            close w
            if reason is "idle" then
                set idle_count to idle_count + 1
            else
                set completed_count to completed_count + 1
            end if
        end try
    end repeat

    if idle_count + completed_count is 0 then
        log "Terminal cleanup: no idle windows found"
    else
        log "Terminal cleanup: " & idle_count & " idle shells + " & completed_count & " completed processes = " & (idle_count + completed_count) & " windows closed"
    end if
end tell
APPLESCRIPT

echo "Cleanup complete."
