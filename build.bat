@echo off
setlocal
chcp 65001 >nul
title 打包 WhatsApp 客户端
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到 .venv，请先运行 setup_windows.bat
    pause
    exit /b 1
)

.venv\Scripts\python.exe -c "import PyInstaller, PyQt6.QtWebEngineWidgets" >nul 2>nul
if errorlevel 1 (
    echo [错误] 缺少打包依赖，请先运行 setup_windows.bat
    pause
    exit /b 1
)

echo 正在打包 Windows 应用...
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --windowed --name WhatsAppClient --icon whatsapp_icon.png --add-data "whatsapp_icon.png;." main.py
if errorlevel 1 (
    echo [错误] 打包失败，请检查上方信息。
    pause
    exit /b 1
)

echo 打包成功：dist\WhatsAppClient\WhatsAppClient.exe
pause
endlocal
