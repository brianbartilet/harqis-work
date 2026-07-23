#!/bin/bash
# Daily smoke tests for harqis-work apps
# Runs pytest smoke-marked tests on apps directory and sends Telegram summary + failures

set -o pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../.." && pwd)
cd "$repo_root"

# Telegram creds come from the gitignored .env/apps.env — never hardcode a
# bot token in a tracked script (it would leak into git history). Pull only
# the two keys we need; don't `source` the whole file (some values contain
# spaces/special chars and would break the shell).
_env=".env/apps.env"
SMOKE_TELEGRAM_NOTIFY="${SMOKE_TELEGRAM_NOTIFY:-1}"
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
if [ "$SMOKE_TELEGRAM_NOTIFY" = "1" ]; then
  TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'")
  TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_DEFAULT_CHAT_ID=' "$_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'")
  if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo "WARN: TELEGRAM_BOT_TOKEN / TELEGRAM_DEFAULT_CHAT_ID not found in $_env; Telegram notifications will be skipped." >&2
  fi
fi

echo "Starting smoke tests..."
start_time=$(date +%s)

# Run only smoke-marked app tests. The full apps/ tree includes sanity/live-cost
# tests that can block on third-party actors or interactive OAuth flows.
# pytest-timeout is an explicit runtime dependency; signal mode aborts hanging
# tests instead of only dumping thread stacks.
mkdir -p results
output_log="results/smoke-tests-output.log"
junit_log="results/smoke-tests-junit.xml"
python_bin="${PYTHON_BIN:-.venv/bin/python}"
rm -f "$junit_log"

if ! "$python_bin" -c 'import pytest_timeout' >/dev/null 2>&1; then
  printf '%s\n' \
    "ERROR: pytest-timeout is unavailable in ${python_bin}." \
    "Install repository requirements before running smoke tests: ${python_bin} -m pip install -r requirements.txt" \
    | tee "$output_log"
  test_status=4
else
  "$python_bin" -m pytest apps/ -m smoke -v --tb=short \
    --timeout="${PYTEST_TIMEOUT:-30}" --timeout-method=signal \
    --junitxml="$junit_log" 2>&1 | tee "$output_log"
  test_status=$?
fi

end_time=$(date +%s)
duration=$((end_time - start_time))

# Prefer pytest's machine-readable JUnit report. The Python fallback parser also
# handles early exits without producing duplicate "0" values in shell variables.
IFS=$'\t' read -r passed failed skipped errors total < <(
  "$python_bin" scripts/agents/testing/smoke_summary.py \
    --junit "$junit_log" --output "$output_log"
)
passed=${passed:-0}
failed=${failed:-0}
skipped=${skipped:-0}
errors=${errors:-0}
total=${total:-0}

if [ "$test_status" -eq 0 ]; then
  status="✅ PASS"
elif [ "$total" -eq 0 ]; then
  status="❌ ERROR"
else
  status="❌ FAIL"
fi

# Create and send summary message to Telegram
summary_msg="🧪 *harqis-work apps smoke tests*
Status: $status
Duration: ${duration}s

Results:
• Executed: $total
• Passed: $passed ✅
• Failed: $failed ❌
• Errors: $errors ⚠️
• Skipped: $skipped ⏭️

Time: $(date '+%Y-%m-%d %H:%M:%S')"

send_telegram() {
  local message="$1"
  if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    return 0
  fi
  curl -sS --fail -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${message}" \
    --data-urlencode "parse_mode=Markdown" >/dev/null \
    || echo "WARN: Telegram smoke-test notification failed." >&2
}

echo "Sending summary to Telegram..."
send_telegram "$summary_msg"

# If there are failures or errors, send detailed analysis
if [ "$failed" -gt 0 ] || [ "$errors" -gt 0 ]; then
  echo "Sending failure/error analysis to Telegram..."

  # Get failures
  failures=$(grep "^FAILED " "$output_log" 2>/dev/null | head -20 | sed 's/^/• /' || echo "No failures listed")

  # Get errors
  error_list=$(grep "^ERROR " "$output_log" 2>/dev/null | head -20 | sed 's/^/• /' || echo "No errors listed")

  analysis_msg="📋 *Test Issues Analysis*"

  if [ "$failed" -gt 0 ]; then
    analysis_msg="$analysis_msg

❌ *Failed Tests:*
$failures"
  fi

  if [ "$errors" -gt 0 ]; then
    analysis_msg="$analysis_msg

⚠️ *Errors:*
$error_list"
  fi

  send_telegram "$analysis_msg"
fi

echo "$summary_msg"
echo "Smoke-test reporting complete."

# Keep results/smoke-tests-output.log for post-run triage.

exit $test_status
