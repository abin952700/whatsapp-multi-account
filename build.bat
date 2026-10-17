@echo off
chcp 65001 >nul
title 打包 WhatsApp 客户端

echo ========================================
echo 正在清理旧的打包文件...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo.
echo 正在启动打包程序，这可能需要几分钟，请耐心等待...
echo ========================================

:: 检查是否有本地虚拟环境，如果有则优先使用虚拟环境里的 pyinstaller
if exist ".venv\Scripts\pyinstaller.exe" (
    .venv\Scripts\pyinstaller.exe --noconfirm --windowed --name WhatsAppClient --icon whatsapp_icon.png main.py
) else (
    pyinstaller --noconfirm --windowed --name WhatsAppClient --icon whatsapp_icon.png main.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] 打包失败！请检查上方报错信息。
    pause
    exit /b
)

echo.
echo ========================================
echo 打包成功！
echo 你的程序在: dist\WhatsAppClient\WhatsAppClient.exe
echo 你可以把整个 WhatsAppClient 文件夹拷贝给别人使用。
echo ========================================
pause