@echo off
call ..\.venv\Scripts\activate.bat
call set_env_workflows.bat

:: Read Flower auth credentials from environment variables
set "FLOWER_USER=%FLOWER_USER%"
set "FLOWER_PASS=%FLOWER_PASS%"

:: Validate that they exist
if "%FLOWER_USER%"=="" (
    echo ERROR: FLOWER_USER environment variable is not set.
    exit /b 1
)

if "%FLOWER_PASS%"=="" (
    echo ERROR: FLOWER_PASS environment variable is not set.
    exit /b 1
)

cd ..
python -m celery -A core.apps.sprout.app.celery:SPROUT flower ^
    --port=5555 ^
    --address=127.0.0.1 ^
    --basic-auth=%FLOWER_USER%:%FLOWER_PASS%

