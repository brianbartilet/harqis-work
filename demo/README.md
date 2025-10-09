# Demo to execute worker and scheduler on different nodes
This is a demo to show how to execute a Dask worker and scheduler 

1. Run the scheduler in one terminal
```bat
@echo off
cd demo
echo Calling set_env.bat...
call .\scripts\set_env.bat

echo Starting scheduler...
python run_tasks.py scheduler
```
2. Run the worker in another terminal
```bat
@echo off
cd demo
echo Calling set_env.bat...
call .\scripts\set_env.bat

echo Starting scheduler...
python run_tasks.py worker
```