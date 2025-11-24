@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ──────────────────────────────────────────────────────────────
REM Get the root path of the git repository FIRST
REM ──────────────────────────────────────────────────────────────
for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set "path_git_root=%%i"
set "path_core=%path_git_root%\core"
set "path_demo=%~dp0"

REM ──────────────────────────────────────────────────────────────
REM Load variables from .env (KEY=VALUE per line)
REM ──────────────────────────────────────────────────────────────
set "ENV_FILE=%path_git_root%\.env\apps.env"

if exist "%ENV_FILE%" (
    echo Loading env vars from "%ENV_FILE%"...
    for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        REM Skip empty keys and comment lines
        set "key=%%A"
        if not "!key!"=="" if not "!key:~0,1!"=="#" (
            set "%%A=%%B"
        )
    )
) else (
    echo WARNING: .env file not found at "%ENV_FILE%"
)

REM ──────────────────────────────────────────────────────────────
REM PYTHONPATH and workflow configs
REM ──────────────────────────────────────────────────────────────
echo Update PYTHONPATH environment variable
set "PYTHONPATH=%path_git_root%;%path_core%;%path_demo%;%PYTHONPATH%"
echo PYTHONPATH updated to %PYTHONPATH%.

echo Set environment variable for workflow configuration
set "WORKFLOW_CONFIG=workflows.config"
echo Environment variable WORKFLOW_CONFIG set to %WORKFLOW_CONFIG%.

echo Set environment variable apps config
set "APP_CONFIG_FILE=apps_config.yaml"

endlocal
