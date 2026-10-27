@echo off
call "%~dp0Run-Python.cmd" "%~dp0scripts\team.py" %*
exit /b %errorlevel%
