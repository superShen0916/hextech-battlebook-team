@echo off
cd /d "%~dp0"
call "%~dp0Run-Python.cmd" "%~dp0scripts\preview_site.py" --share
