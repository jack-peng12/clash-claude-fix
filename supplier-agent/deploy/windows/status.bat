@echo off
call "%~dp0_common.bat" || exit /b 1
docker compose ps
echo ---- 最近日志 ----
docker compose logs --tail 40 agent
popd
pause
