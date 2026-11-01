@echo off
call "%~dp0_common.bat" || exit /b 1
echo 可用备份：
dir /b "data\backups\backup_*.zip"
set /p BK=请输入要恢复的备份文件名（例如 backup_20260101_120000.zip）:
if not exist "data\backups\%BK%" (
  echo 文件不存在。
  popd
  pause
  exit /b 1
)
echo 恢复将覆盖当前数据。先自动备份当前数据...
docker compose exec -T agent python -m app.services.backup
docker compose stop agent
docker compose run --rm --no-deps agent python -m app.services.backup restore "/data/backups/%BK%" || goto :fail
docker compose up -d agent
echo 恢复完成。
popd
pause
exit /b 0
:fail
echo [失败] 恢复出错，服务未重新启动。请联系技术支持。
popd
pause
exit /b 1
