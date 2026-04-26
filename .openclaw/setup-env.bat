@echo off
REM OpenClaw Environment Setup Script (Windows batch)
REM This script configures OPENCLAW_CONFIG_PATH and OPENCLAW_STATE_DIR

setlocal enabledelayedexpansion

REM Set defaults
set "SYNC_REPO=%~dp0workspace"
set "PROFILE=default"
set "PERMANENT="

REM Parse arguments
:parse_args
if "%~1"=="" goto done_parsing
if "%~1"=="--help" goto show_help
if "%~1"=="-h" goto show_help
if "%~1"=="--sync-repo" (
    set "SYNC_REPO=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--profile" (
    set "PROFILE=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--permanent" (
    set "PERMANENT=1"
    shift
    goto parse_args
)
shift
goto parse_args

:show_help
echo Usage: setup-env.bat [options]
echo.
echo Options:
echo   --sync-repo ^<path^>   Path to the sync repository (default: .\.openclaw\workspace^)
echo   --profile ^<name^>     OpenClaw profile name (default: default^)
echo   --permanent          Save to user environment variables ^(requires admin^)
echo   --help, -h           Display this help message
echo.
echo Examples:
echo   setup-env.bat
echo   setup-env.bat --sync-repo "D:\my-openclaw-sync" --permanent
echo.
exit /b 0

:done_parsing
REM Validate sync repo exists
if not exist "%SYNC_REPO%" (
    echo Error: Sync repository path not found: %SYNC_REPO%
    exit /b 1
)

REM Create directories
set "CONFIG_PATH=%SYNC_REPO%\config"
set "STATE_PATH=%SYNC_REPO%\state"

if not exist "%CONFIG_PATH%" (
    mkdir "%CONFIG_PATH%"
    echo Created: %CONFIG_PATH%
)

if not exist "%STATE_PATH%" (
    mkdir "%STATE_PATH%"
    echo Created: %STATE_PATH%
)

REM Set environment variables for current session
set "OPENCLAW_CONFIG_PATH=%CONFIG_PATH%"
set "OPENCLAW_STATE_DIR=%STATE_PATH%"

if not "%PROFILE%"=="default" (
    set "OPENCLAW_PROFILE=%PROFILE%"
)

echo.
echo Environment variables set for current session:
echo   OPENCLAW_CONFIG_PATH=%CONFIG_PATH%
echo   OPENCLAW_STATE_DIR=%STATE_PATH%
if not "%PROFILE%"=="default" (
    echo   OPENCLAW_PROFILE=%PROFILE%
)

REM Optionally save permanently
if not "%PERMANENT%"=="" (
    REM Check for admin privileges
    net session >nul 2>&1
    if errorlevel 1 (
        echo.
        echo Error: --permanent flag requires administrator privileges
        echo Please run this script as Administrator and try again
        exit /b 1
    )

    REM Set user environment variables
    setx OPENCLAW_CONFIG_PATH "%CONFIG_PATH%"
    setx OPENCLAW_STATE_DIR "%STATE_PATH%"
    
    if not "%PROFILE%"=="default" (
        setx OPENCLAW_PROFILE "%PROFILE%"
    )

    echo.
    echo Environment variables saved permanently to user profile
    echo Note: You may need to restart applications for new environment variables to take effect
)

echo.
echo Setup complete!
echo OpenClaw will now use this sync repo for configuration and state persistence
