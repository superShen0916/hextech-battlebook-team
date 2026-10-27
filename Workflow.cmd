@echo off
call "%~dp0Run-Python.cmd" "%~dp0scripts\workflow.py" %*
exit /b %errorlevel%
