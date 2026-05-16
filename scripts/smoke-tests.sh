#!/bin/bash
# Daily smoke tests for harqis-work apps
# Runs pytest on apps directory and sends Telegram summary

cd /Users/harqis-one/GIT/harqis-work

echo "Starting smoke tests..."
start_time=$(date +%s)

# Run pytest on apps directory with json report
.venv/bin/pytest apps/ -v --tb=short 2>&1 | tee smoke-tests-output.log
test_status=$?

end_time=$(date +%s)
duration=$((end_time - start_time))

# Parse results
if [ $test_status -eq 0 ]; then
    status="✅ PASS"
else
    status="❌ FAIL"
fi

# Get test counts
passed=$(grep -c "PASSED" smoke-tests-output.log || echo 0)
failed=$(grep -c "FAILED" smoke-tests-output.log || echo 0)
skipped=$(grep -c "SKIPPED" smoke-tests-output.log || echo 0)

# Create summary
summary="Smoke Tests Report
================
Status: $status
Duration: ${duration}s

Results:
- Passed: $passed
- Failed: $failed
- Skipped: $skipped

Run at: $(date)
"

echo "$summary"

# Clean up temp files
rm -f smoke-tests-output.log

exit $test_status
