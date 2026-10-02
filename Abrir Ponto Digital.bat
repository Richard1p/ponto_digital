@echo off
setlocal
cd /d "%~dp0"

where pythonw.exe >nul 2>&1
if errorlevel 1 goto iniciar_visivel

python -c "import importlib.util,sys; sys.exit(not all(importlib.util.find_spec(m) for m in ('flask','holidays')))" >nul 2>&1
if errorlevel 1 goto iniciar_visivel

start "" /b pythonw.exe "%~dp0app.py" >nul 2>&1
endlocal
exit /b 0

:iniciar_visivel
call "%~dp0iniciar.bat"
