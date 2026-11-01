@echo off
chcp 65001 >nul
rem Locate the folder that contains docker-compose.yml (package root or source tree root).
set "SA_ROOT=%~dp0"
if not exist "%SA_ROOT%docker-compose.yml" set "SA_ROOT=%~dp0..\..\"
pushd "%SA_ROOT%"
docker version >nul 2>&1
if errorlevel 1 (
  echo [错误] 未检测到 Docker。请先安装并启动 Docker Desktop，然后重试。
  echo        下载地址: https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)
