@echo off
REM Get the root path of the git repository
for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set "path_git_root=%%i"
set "path_core=%path_git_root%\core"
set "path_demo=%~dp0"

echo Update PYTHONPATH environment variable
set "PYTHONPATH=%path_git_root%;%path_core%;%path_demo%;%PYTHONPATH%"
echo PYTHONPATH updated to %PYTHONPATH%.

echo Set environment variable for workflow configuration
set "WORKFLOW_CONFIG=workflows.config"

echo Environment variable WORKFLOW_CONFIG set to %WORKFLOW_CONFIG%.
