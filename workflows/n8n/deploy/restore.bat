@echo off
setlocal ENABLEDELAYEDEXPANSION

echo [INFO] n8n restore starting...

set "SCRIPT_DIR=%~dp0"
set "COMPOSE_FILE=%SCRIPT_DIR%docker-compose.yml"
set "BACKUP_DIR=%SCRIPT_DIR%..\backups"
set "VOLUME_NAME=deploy_n8n_data"

if not exist "%COMPOSE_FILE%" (
    echo [ERROR] docker-compose.yml not found at: %COMPOSE_FILE%
    exit /b 1
)

if not exist "%BACKUP_DIR%" (
    echo [ERROR] Backup directory not found: %BACKUP_DIR%
    exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] docker is not installed or not in PATH.
    exit /b 1
)

REM Pick docker compose command
docker compose version >nul 2>&1
if %errorlevel%==0 (
    set "DC=docker compose"
) else (
    set "DC=docker-compose"
)

REM ---------- choose backup file ----------
set "BACKUP_FILE="

if "%~1"=="" (
    REM Use latest backup-*.tgz
    for /f "delims=" %%F in ('dir /b /o:-d "%BACKUP_DIR%\backup-*.tgz" 2^>nul') do (
        set "BACKUP_FILE=%BACKUP_DIR%\%%F"
        goto got_backup
    )
) else (
    set "ARG1=%~1"
    echo %ARG1% | findstr /i ".tgz$" >nul
    if %errorlevel%==0 (
        set "BACKUP_FILE=%BACKUP_DIR%\%ARG1%"
    ) else (
        set "BACKUP_FILE=%BACKUP_DIR%\%ARG1%.tgz"
    )
)

:got_backup

if not defined BACKUP_FILE (
    echo [ERROR] No backup file found.
    echo         Make sure there are files like "%BACKUP_DIR%\backup-*.tgz"
    exit /b 1
)

if not exist "%BACKUP_FILE%" (
    echo [ERROR] Backup file not found: %BACKUP_FILE%
    exit /b 1
)

echo [INFO] Using backup file: %BACKUP_FILE%

REM ---------- stop container ----------
echo [INFO] Stopping n8n container...
%DC% -f "%COMPOSE_FILE%" down

REM ---------- recreate volume ----------
echo [INFO] Recreating Docker volume "%VOLUME_NAME%"...
docker volume rm -f %VOLUME_NAME% >nul 2>&1
docker volume create %VOLUME_NAME% >nul

REM ---------- restore into volume ----------
echo [INFO] Restoring backup into volume "%VOLUME_NAME%"...
docker run --rm ^
  -v %VOLUME_NAME%:/data ^
  -v "%BACKUP_FILE%:/backup.tgz" ^
  alpine sh -c "cd /data && tar xzf /backup.tgz"

echo [INFO] Restore into volume complete.

REM ---------- start container ----------
echo [INFO] Starting n8n container...
%DC% -f "%COMPOSE_FILE%" up -d

echo [INFO] Waiting for n8n container to be healthy...

REM Wait until container is listed and running (max 30 seconds)
set /A _WAIT=0
:wait_loop
for /f "tokens=2" %%s in ('docker ps --filter "name=n8n" --format "{{.Status}}"') do (
    echo %%s | findstr /i "Up" >nul
    if not errorlevel 1 (
        echo [INFO] n8n container is running.
        goto done_wait
    )
)

REM Sleep 2 seconds
powershell -NoLogo -Command "Start-Sleep -Seconds 2" >nul
set /A _WAIT+=2

if %_WAIT% GEQ 30 (
    echo [WARN] n8n container did not become 'Up' within 30 seconds.
    goto done_wait
)

goto wait_loop

:done_wait
echo [OK] Restore finished. n8n should now be running with restored data.
endlocal
