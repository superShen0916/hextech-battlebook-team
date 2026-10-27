@echo off
cd /d "%~dp0"
call "%~dp0Run-Python.cmd" "%~dp0work\gopher-pilot-20261021\scripts\sync_new_matches.py" --yes
exit /b %errorlevel%
