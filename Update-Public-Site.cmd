@echo off
cd /d "%~dp0"
if not "%~1"=="" goto custom
call "%~dp0Run-Python.cmd" "%~dp0scripts\build_release.py" --data-only --sync
goto checked
:custom
call "%~dp0Run-Python.cmd" "%~dp0scripts\build_release.py" --sync %*
:checked
if errorlevel 1 exit /b %errorlevel%
echo Verified release files are ready in outputs\public-site-20261022b.
echo Publish that existing application in WorkBuddy. This does not update GPT Sites.
pause
