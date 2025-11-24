@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ──────────────────────────────────────────────────────────────
REM Determine Git repo root FIRST
REM ──────────────────────────────────────────────────────────────
for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set "path_git_root=%%i"
set "path_core=%path_git_root%\core"
set "path_demo=%~dp0"

REM ──────────────────────────────────────────────────────────────
REM Load variables from .env/apps.env
REM ──────────────────────────────────────────────────────────────
set "ENV_FILE=%path_git_root%\.env\apps.env"

if exist "%ENV_FILE%" (
    echo Loading env vars from "%ENV_FILE%"...
    for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        set "key=%%A"
        if not "!key!"=="" if not "!key:~0,1!"=="#" (
            set "%%A=%%B"
        )
    )
) else (
    echo WARNING: .env file not found at "%ENV_FILE%"
)

REM ──────────────────────────────────────────────────────────────
REM Python / Sprout runtime paths
REM ──────────────────────────────────────────────────────────────
echo Updating PYTHONPATH...
set "PYTHONPATH=%path_git_root%;%path_core%;%path_demo%;%PYTHONPATH%"

echo Setting workflow configuration...
set "WORKFLOW_CONFIG=workflows.config"

echo Setting APP_CONFIG_FILE...
set "APP_CONFIG_FILE=apps_config.yaml"

REM Continue to worker startup (your original script continues here)

endlocal
