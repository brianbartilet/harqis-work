@echo off
setlocal enabledelayedexpansion

REM ─────────────────────────────────────────────────────────────────────────────
REM set_env_worker_remote.bat — Configure environment for REMOTE worker nodes.
REM
REM Unlike set_env_workflows.bat, this script does NOT load apps.env or set
REM PATH_APP_CONFIG. Config is fetched from the host at startup via Redis or HTTP.
REM
REM Call this script from a worker runner: call set_env_worker_remote.bat
REM
REM Required env vars — set these on the remote machine before calling, or put
REM them in .env\worker.env (see .env\worker.env.example):
REM
REM   CONFIG_SOURCE        redis | http
REM   CELERY_BROKER_URL    amqp://guest:guest@<host-ip>:5672/
REM
REM   Redis mode:
REM     CONFIG_REDIS_URL   redis://<host-ip>:6379/1
REM     CONFIG_REDIS_KEY   (optional, default: harqis:config)
REM
REM   HTTP mode:
REM     CONFIG_SERVER_URL    http://<host-ip>:8765
REM     CONFIG_SERVER_TOKEN  (must match host server token)
REM ─────────────────────────────────────────────────────────────────────────────

for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set "path_git_root=%%i"
echo Git root: %path_git_root%

REM ── Load .env\worker.env if present ─────────────────────────────────────────
set "WORKER_ENV=%path_git_root%\.env\worker.env"
if exist "%WORKER_ENV%" (
    echo Loading %WORKER_ENV%...
    for /f "usebackq tokens=1,* delims==" %%A in ("%WORKER_ENV%") do (
        set "key=%%A"
        if not "!key!"=="" if not "!key:~0,1!"=="#" (
            set "%%A=%%B"
        )
    )
)

REM ── Validate required vars ───────────────────────────────────────────────────
if not defined CONFIG_SOURCE (
    echo ERROR: CONFIG_SOURCE must be set to 'redis' or 'http' >&2
    exit /b 1
)
if not defined CELERY_BROKER_URL (
    echo ERROR: CELERY_BROKER_URL must point to the host RabbitMQ >&2
    exit /b 1
)
if "%CONFIG_SOURCE%"=="redis" (
    if not defined CONFIG_REDIS_URL (
        echo ERROR: CONFIG_REDIS_URL required when CONFIG_SOURCE=redis >&2
        exit /b 1
    )
)
if "%CONFIG_SOURCE%"=="http" (
    if not defined CONFIG_SERVER_URL (
        echo ERROR: CONFIG_SERVER_URL required when CONFIG_SOURCE=http >&2
        exit /b 1
    )
)

REM ── Python / workflow paths ──────────────────────────────────────────────────
set "PYTHONPATH=%path_git_root%;%PYTHONPATH%"
set "ROOT_DIRECTORY=%path_git_root%"
set "WORKFLOW_CONFIG=workflows.config"
set "APP_CONFIG_FILE=apps_config.yaml"

echo CONFIG_SOURCE     = %CONFIG_SOURCE%
echo CELERY_BROKER_URL = %CELERY_BROKER_URL%
echo ROOT_DIRECTORY    = %ROOT_DIRECTORY%
echo Remote worker environment ready.
