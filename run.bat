@echo off
REM run.bat — git pull, then deploy via scripts/deploy.py.
REM Auto-detects this machine via scripts/machines.toml.
REM Use scripts/deploy.py directly for advanced flags (--down, --status, --register).

setlocal
echo.
echo ================================
echo   Updating Codebase
echo ================================
git pull

echo.
echo ================================
echo   Deploying
echo ================================
.\.venv\Scripts\python.exe scripts\deploy.py %*

endlocal
