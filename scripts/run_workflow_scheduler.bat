@echo off
call ..\.venv\Scripts\activate.bat
call set_env_workflows.bat

cd ..


echo Starting scheduler...
python run_workflows.py scheduler >> scheduler.log 2>&1
