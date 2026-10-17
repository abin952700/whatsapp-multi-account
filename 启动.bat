@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul && set "PYTHON_BIN=py -3"
    if not defined PYTHON_BIN set "PYTHON_BIN=python"
)

%PYTHON_BIN% -c "import PyQt6.QtWebEngineWidgets" >nul 2>nul
if errorlevel 1 (
    echo [错误] 缺少运行依赖，请先双击 setup_windows.bat
    pause
    exit /b 1
)

%PYTHON_BIN% main.py %*
endlocal
