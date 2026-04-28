@echo off
REM run_workflow_worker_remote_tcg.bat — Start the TCG queue worker on a remote node.
REM Config is fetched from the host (Redis or HTTP) — no local apps.env needed.

call ..\.venv\Scripts\activate.bat
call set_env_worker_remote.bat

cd ..

set "WORKFLOW_QUEUE=tcg"

echo Starting remote worker (queue: %WORKFLOW_QUEUE%, config: %CONFIG_SOURCE%)...
python run_workflows.py worker
