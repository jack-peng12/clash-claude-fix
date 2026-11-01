@echo off
call "%~dp0_common.bat" || exit /b 1
docker compose up -d agent && echo 已启动: http://localhost:8000
popd
pause
