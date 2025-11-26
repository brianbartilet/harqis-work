@echo off
REM Initialize Apache Airflow (DB + admin user)

REM Change this to the folder where your docker-compose.yml is
set AIRFLOW_HOME=C:\airflow

REM Optional but harmless: UID placeholder for Airflow
set AIRFLOW_UID=50000

cd /d "%AIRFLOW_HOME%"

echo Initializing Airflow database and creating admin user...
docker compose up airflow-init

echo.
echo Initialization complete. Press any key to continue...
pause >nul
