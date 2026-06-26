@echo off
setlocal ENABLEDELAYEDEXPANSION

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..\..") do set "REPO_ROOT=%%~fI"
set "BACKUP_DIR=%SCRIPT_DIR%..\backups"

if defined HARQIS_DATA_ROOT (
    for %%I in ("%HARQIS_DATA_ROOT%") do set "DATA_ROOT=%%~fI"
) else (
    set "DATA_ROOT=%REPO_ROOT%\.harqis-data"
)
set "N8N_DATA_DIR=%DATA_ROOT%\n8n"

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] docker is not installed or not in PATH.
    exit /b 1
)

if not exist "%N8N_DATA_DIR%" (
    echo [ERROR] n8n data directory does not exist: %N8N_DATA_DIR%
    echo         This should match docker-compose.yml: ${HARQIS_DATA_ROOT:-./.harqis-data}/n8n:/home/node/.n8n
    exit /b 1
)

if not exist "%N8N_DATA_DIR%\database.sqlite" (
    echo [ERROR] n8n database not found: %N8N_DATA_DIR%\database.sqlite
    exit /b 1
)

REM ---------- verify database health before backing up ----------
echo [INFO] Verifying SQLite database health in %N8N_DATA_DIR%...
for /f "delims=" %%R in ('docker run --rm -v "%N8N_DATA_DIR%:/data:ro" alpine sh -c "apk add --no-cache sqlite >/dev/null 2>&1 && sqlite3 /data/database.sqlite \"SELECT COUNT(*) FROM workflow_entity;\" 2>&1"') do set "DB_CHECK=%%R"
echo %DB_CHECK% | findstr /i "error corrupt malformed" >nul
if not errorlevel 1 (
    echo [ERROR] Database health check failed: %DB_CHECK%
    echo         Run restore.bat first to repair the database before taking a backup.
    exit /b 1
)
echo [INFO] Database OK ^(workflow count: %DB_CHECK%^)

for /f %%a in ('powershell -NoLogo -Command "(Get-Date).ToString(\"yyyyMMdd-HHmmss\")"') do set "DATESTAMP=%%a"
set "BACKUP_NAME=backup-%DATESTAMP%.tgz"
set "BACKUP_PATH=%BACKUP_DIR%\%BACKUP_NAME%"

echo [INFO] Creating backup of n8n data directory "%N8N_DATA_DIR%" -^> %BACKUP_PATH%

docker run --rm ^
  -v "%N8N_DATA_DIR%:/data:ro" ^
  -v "%BACKUP_DIR%:/backup" ^
  alpine sh -c "cd /data && tar czf /backup/%BACKUP_NAME% ."

echo [OK] Backup created: %BACKUP_PATH%
endlocal
