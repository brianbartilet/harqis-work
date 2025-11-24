@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "BACKUP_DIR=%SCRIPT_DIR%..\backups"
set "VOLUME_NAME=deploy_n8n_data"

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
