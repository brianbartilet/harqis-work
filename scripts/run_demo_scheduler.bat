@echo off
call ..\.venv\Scripts\activate.bat
call set_env.bat

cd ..\demo

echo Starting scheduler...
python run_tasks.py scheduler
