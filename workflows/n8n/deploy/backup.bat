@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "BACKUP_DIR=%SCRIPT_DIR%..\backups"
set "VOLUME_NAME=harqis-work_n8n_data"

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] docker is not installed or not in PATH.
    exit /b 1
)

docker volume inspect %VOLUME_NAME% >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker volume "%VOLUME_NAME%" does not exist.
    exit /b 1
)

REM ---------- verify database health before backing up ----------
echo [INFO] Verifying SQLite database health...
for /f "delims=" %%R in ('docker run --rm -v %VOLUME_NAME%:/data alpine sh -c "apk add --no-cache sqlite >/dev/null 2>&1 && sqlite3 /data/database.sqlite \"SELECT COUNT(*) FROM workflow_entity;\" 2>&1"') do set "DB_CHECK=%%R"
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

echo [INFO] Creating backup of volume "%VOLUME_NAME%" -> %BACKUP_PATH%

docker run --rm ^
  -v %VOLUME_NAME%:/data ^
  -v "%BACKUP_DIR%:/backup" ^
  alpine sh -c "cd /data && tar czf /backup/%BACKUP_NAME% ."

echo [OK] Backup created: %BACKUP_PATH%
endlocal
