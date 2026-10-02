@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python nao foi encontrado. Instale o Python e habilite a opcao Add Python to PATH.
    pause
    exit /b 1
)

python -c "import importlib.util,sys; sys.exit(not all(importlib.util.find_spec(m) for m in ('flask','holidays')))" >nul 2>&1
if errorlevel 1 (
    echo Instalando as dependencias do Controle de Horas 2.0...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Nao foi possivel instalar as dependencias.
        pause
        exit /b 1
    )
)

python app.py
if errorlevel 1 pause
endlocal
