@echo off
setlocal
set "PYTHONUTF8=1"
set "MAYHEM_PYTHON=D:\AI-Workspace\toolchains\python\cpython-3.12.15-windows-x86_64-none\python.exe"
set "MAYHEM_PREFIX="
if exist "%MAYHEM_PYTHON%" goto run
where py.exe >nul 2>nul
if not errorlevel 1 goto use_launcher
where python.exe >nul 2>nul
if not errorlevel 1 goto use_python
echo Python 3.10+ is required. Install Python, then try again.
exit /b 5
:use_launcher
set "MAYHEM_PYTHON=py.exe"
set "MAYHEM_PREFIX=-3"
goto run
:use_python
set "MAYHEM_PYTHON=python.exe"
:run
"%MAYHEM_PYTHON%" %MAYHEM_PREFIX% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 5)"
if errorlevel 1 exit /b 5
"%MAYHEM_PYTHON%" %MAYHEM_PREFIX% %*
exit /b %errorlevel%
