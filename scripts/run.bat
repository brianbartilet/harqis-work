@echo off
git pull
.\.venv\Scripts\pip.exe install -r requirements.txt --force-reinstall

cd ..\scripts
call run_workflow_scheduler

cd ..\scripts
call run_workflow_worker