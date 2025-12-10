@echo off
call ..\.venv\Scripts\activate.bat
call set_env_workflows.bat

cd ..

set "WORKFLOW_QUEUE=tcg"

echo Starting worker...
python run_workflows.py worker
