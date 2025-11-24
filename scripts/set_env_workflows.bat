@echo off

REM ──────────────────────────────────────────────────────────────
REM Get the root path of the git repository FIRST
REM ──────────────────────────────────────────────────────────────
for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set "path_git_root=%%i"
set "path_demo=%~dp0"

echo Git root detected: %path_git_root%

REM ──────────────────────────────────────────────────────────────
REM Load variables from .env (KEY=VALUE per line)
REM Expect: %path_git_root%\.env\apps.env
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
REM Portable paths for Python / Sprout / configs
REM ──────────────────────────────────────────────────────────────

echo Update PYTHONPATH environment variable
set "PYTHONPATH=%path_git_root%;%path_demo%;%PYTHONPATH%"
echo PYTHONPATH updated to %PYTHONPATH%.

REM Root directory of the application (used by ENV_ROOT_DIRECTORY)
set "ROOT_DIRECTORY=%path_git_root%"

REM App config base directory (used by ENV_APP_CONFIG)
set "PATH_APP_CONFIG=%path_git_root%"

REM Where secrets / .env live (used by ENV_APP_SECRETS)
set "PATH_APP_CONFIG_SECRETS=%path_git_root%\.env"

REM Workflow config module for Sprout/Celery dynamic import
REM Sprout will call get_env_variable_value(ENV_WORKFLOW_CONFIG)
REM -> resolves to env var WORKFLOW_CONFIG
set "WORKFLOW_CONFIG=workflows.config"
echo Environment variable WORKFLOW_CONFIG set to %WORKFLOW_CONFIG%.

REM Which apps config file to use (your loader default)
set "APP_CONFIG_FILE=apps_config.yaml"
echo Environment variable APP_CONFIG_FILE set to %APP_CONFIG_FILE%.
