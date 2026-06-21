#!/bin/bash
# Daily smoke tests for harqis-work apps
# Runs pytest smoke-marked tests on apps directory and sends Telegram summary + failures

set -o pipefail

cd /Users/harqis-one/GIT/harqis-work

# Telegram creds come from the gitignored .env/apps.env — never hardcode a
# bot token in a tracked script (it would leak into git history). Pull only
# the two keys we need; don't `source` the whole file (some values contain
# spaces/special chars and would break the shell).
_env=".env/apps.env"
TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'")
TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_DEFAULT_CHAT_ID=' "$_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'")
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
  echo "WARN: TELEGRAM_BOT_TOKEN / TELEGRAM_DEFAULT_CHAT_ID not found in $_env; Telegram notifications will be skipped." >&2
fi

echo "Starting smoke tests..."
start_time=$(date +%s)

# Run only smoke-marked app tests. The full apps/ tree includes sanity/live-cost
# tests that can block on third-party actors or interactive OAuth flows.
# pytest-timeout is installed in the runtime venv; signal mode aborts hanging
# tests instead of only dumping thread stacks.
mkdir -p results
output_log="results/smoke-tests-output.log"
.venv/bin/pytest apps/ -m smoke -v --tb=short --timeout="${PYTEST_TIMEOUT:-30}" --timeout-method=signal 2>&1 | tee "$output_log"
test_status=$?

end_time=$(date +%s)
duration=$((end_time - start_time))

# Parse results BEFORE deleting log file
# Extract from pytest summary line: "====== X failed, Y passed, Z skipped, N errors ======="
summary_line=$(grep -E '(^=+ .* (passed|failed|skipped|error|errors|deselected).* in .*=+$|^=+ no tests ran in .*=+$)' "$output_log" 2>/dev/null | tail -1 || echo "")

# Extract counts from summary using regex
passed=$(echo "$summary_line" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
failed=$(echo "$summary_line" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo 0)
skipped=$(echo "$summary_line" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+' || echo 0)
errors=$(echo "$summary_line" | grep -oE '[0-9]+ errors?' | grep -oE '[0-9]+' || echo 0)

# Fallback to grep if summary line parsing fails
if [ -z "$passed" ] || [ "$passed" = "0" ]; then
  passed=$(grep -c "PASSED" "$output_log" 2>/dev/null || echo 0)
  failed=$(grep -c "FAILED" "$output_log" 2>/dev/null || echo 0)
  skipped=$(grep -c "SKIPPED" "$output_log" 2>/dev/null || echo 0)
  errors=$(grep "^ERROR " "$output_log" 2>/dev/null | grep -c "ERROR" || echo 0)
fi

# Parse results
if [ $test_status -eq 0 ]; then
    status="✅ PASS"
else
    status="❌ FAIL"
fi

# Create and send summary message to Telegram
summary_msg="🧪 *harqis-work apps smoke tests*
Status: $status
Duration: ${duration}s

Results:
• Passed: $passed ✅
• Failed: $failed ❌
• Errors: $errors ⚠️
• Skipped: $skipped ⏭️

Time: $(date '+%Y-%m-%d %H:%M:%S')"

echo "Sending summary to Telegram..."
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  -d "text=${summary_msg}" \
  -d "parse_mode=Markdown" > /dev/null

# If there are failures or errors, send detailed analysis
if [ $failed -gt 0 ] || [ $errors -gt 0 ]; then
  echo "Sending failure/error analysis to Telegram..."

  # Get failures
  failures=$(grep "^FAILED " "$output_log" 2>/dev/null | head -20 | sed 's/^/• /' || echo "No failures listed")

  # Get errors
  error_list=$(grep "^ERROR " "$output_log" 2>/dev/null | head -20 | sed 's/^/• /' || echo "No errors listed")

  analysis_msg="📋 *Test Issues Analysis*"

  if [ $failed -gt 0 ]; then
    analysis_msg="$analysis_msg

❌ *Failed Tests:*
$failures"
  fi

  if [ $errors -gt 0 ]; then
    analysis_msg="$analysis_msg

⚠️ *Errors:*
$error_list"
  fi

  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=${analysis_msg}" \
    -d "parse_mode=Markdown" > /dev/null
fi

echo "$summary_msg"
echo "Telegram messages sent."

# Keep results/smoke-tests-output.log for post-run triage.

exit $test_status
