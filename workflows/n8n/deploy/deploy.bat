@echo off
setlocal ENABLEDELAYEDEXPANSION

echo [INFO] n8n deploy starting...

set "SCRIPT_DIR=%~dp0"
set "COMPOSE_FILE=%SCRIPT_DIR%docker-compose.yml"
set "OLD_DATA_DIR=%SCRIPT_DIR%..\backups\n8n"
set "VOLUME_NAME=deploy_n8n_data"

if not exist "%COMPOSE_FILE%" (
    echo [ERROR] docker-compose.yml not found at: %COMPOSE_FILE%
    exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] docker is not installed or not in PATH.
    exit /b 1
)

REM pick docker compose vs docker-compose
docker compose version >nul 2>&1
if %errorlevel%==0 (
    set "DC=docker compose"
) else (
    set "DC=docker-compose"
)

REM ensure volume
docker volume inspect %VOLUME_NAME% >nul 2>&1
if errorlevel 1 (
    echo [INFO] Creating Docker volume "%VOLUME_NAME%"...
    docker volume create %VOLUME_NAME% >nul
) else (
    echo [INFO] Docker volume "%VOLUME_NAME%" already exists.
)

REM one-time migration from old folder if it exists
if exist "%OLD_DATA_DIR%" (
    dir /b "%OLD_DATA_DIR%" >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Found previous data in "%OLD_DATA_DIR%".
        echo [INFO] Copying its contents into volume "%VOLUME_NAME%"...

        docker run --rm ^
          -v %VOLUME_NAME%:/data ^
          -v "%OLD_DATA_DIR%:/source" ^
          alpine sh -c "cd /source && cp -a . /data"

        echo [INFO] Migration copy finished.
    ) else (
        echo [INFO] "%OLD_DATA_DIR%" is empty. Skipping migration.
    )
) else (
    echo [INFO] No previous bind-mounted data directory found to migrate.
)

REM start n8n
echo [INFO] Starting n8n via docker compose...
%DC% -f "%COMPOSE_FILE%" up -d

echo [OK] n8n deploy complete.
endlocal
