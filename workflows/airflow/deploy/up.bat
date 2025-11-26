@echo off
REM Start Apache Airflow stack (webserver, scheduler, worker, flower)

set AIRFLOW_HOME=C:\airflow
set AIRFLOW_UID=50000

cd /d "%AIRFLOW_HOME%"

echo Starting Airflow services...
docker compose up -d

echo.
echo Airflow is starting. Web UI: http://localhost:8080
echo Flower (Celery): http://localhost:5555
echo.
pause
