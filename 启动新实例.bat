@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "dist\WhatsAppClient\WhatsAppClient.exe" (
    if "%~1"=="" (
        start "" "dist\WhatsAppClient\WhatsAppClient.exe"
    ) else (
        start "" "dist\WhatsAppClient\WhatsAppClient.exe" --instance "%~1"
    )
) else (
    if "%~1"=="" (
        start "" "启动.bat"
    ) else (
        start "" "启动.bat" --instance "%~1"
    )
)
endlocal
