@echo off
call "%~dp0_common.bat" || exit /b 1
docker compose stop agent && echo 已停止。后台任务将在下次启动后自动继续。
popd
pause
