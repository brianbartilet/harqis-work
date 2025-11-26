@echo off
REM WARNING: This will remove ALL Airflow data (DB, logs in volumes)

set AIRFLOW_HOME=C:\airflow

cd /d "%AIRFLOW_HOME%"

echo This will REMOVE Airflow volumes (database, etc.).
echo Press Ctrl+C to cancel.
pause

docker compose down -v

echo.
echo Airflow has been reset. You must run airflow_init.bat again.
pause
