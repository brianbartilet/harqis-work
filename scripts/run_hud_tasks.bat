@echo off
call ..\.venv\Scripts\activate.bat
call set_env_workflows.bat



python ..\workflows\n8n\utilities\send_flower_task.py --send-all --queue hud --user harqistesting --password H3ll0p0z1v23