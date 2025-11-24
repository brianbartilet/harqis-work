@echo off
git pull
REM .\.venv\Scripts\pip.exe install -r requirements.txt --force-reinstall

call .\scripts\run_workflow_scheduler


call .\scripts\run_workflow_worker