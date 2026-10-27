@echo off
call "%~dp0Run-Python.cmd" "%~dp0scripts\node_runtime.py" %*
exit /b %errorlevel%
