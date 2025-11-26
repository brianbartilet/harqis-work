@echo off
REM Stop Apache Airflow containers (keep data)

set AIRFLOW_HOME=C:\airflow

cd /d "%AIRFLOW_HOME%"

echo Stopping Airflow services...
docker compose down

echo.
echo Airflow services stopped.
pause
