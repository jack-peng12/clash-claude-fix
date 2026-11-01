@echo off
call "%~dp0_common.bat" || exit /b 1
echo 升级前自动备份...
docker compose exec -T agent python -m app.services.backup
if exist "images\supplier-agent.tar" (
  docker load -i "images\supplier-agent.tar" || goto :fail
) else (
  docker compose build || goto :fail
)
docker compose up -d agent || goto :fail
echo 升级完成。数据库表结构在启动时自动补齐；如升级后异常，可用 restore.bat 恢复升级前备份。
popd
pause
exit /b 0
:fail
echo [失败] 升级未完成，原版本数据未改动。
popd
pause
exit /b 1
