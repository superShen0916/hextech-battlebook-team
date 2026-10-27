@echo off
cd /d "%~dp0"
call Run-Python.cmd app\main.py recover --rounds 2 --skip-timelines
pause
