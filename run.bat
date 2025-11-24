@echo off
setlocal

echo.
echo ================================
echo   Updating Codebase
echo ================================
echo.

echo Running git pull...
git pull

echo.
echo Installing Python requirements...
REM .\.venv\Scripts\pip.exe install -r requirements.txt --force-reinstall

echo Activate environment
.\.venv\Scripts\activate

echo.
echo ================================
echo   Starting Processes
echo ================================
echo.

echo Starting celery scheduler in new window...
cd .\scripts
start "scheduler" cmd /k "run_workflow_scheduler.bat"

echo Starting celery worker in new window...
cd .\scripts
start "worker" cmd /k "run_workflow_worker.bat"

echo.
echo All processes started in separate windows.
endlocal
