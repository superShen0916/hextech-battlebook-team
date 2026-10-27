@echo off
cd /d "%~dp0"
call "%~dp0Sync-History.cmd"
if errorlevel 1 exit /b %errorlevel%
call "%~dp0Update-Public-Site.cmd"
