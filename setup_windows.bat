@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_BIN=py -3"
) else (
    set "PYTHON_BIN=python"
)

echo 正在创建 Windows 虚拟环境...
%PYTHON_BIN% -m venv .venv
if errorlevel 1 goto :error

echo 正在安装依赖...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Windows 环境安装完成。
pause
exit /b 0

:error
echo [错误] Windows 环境安装失败。
pause
exit /b 1
