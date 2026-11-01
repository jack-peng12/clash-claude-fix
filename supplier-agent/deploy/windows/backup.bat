@echo off
call "%~dp0_common.bat" || exit /b 1
echo 正在备份（数据库+密钥+网页证据）...
docker compose exec -T agent python -m app.services.backup || goto :fail
echo 备份文件位于 data\backups\ 目录，建议定期复制到U盘或其他电脑。
explorer "data\backups"
popd
pause
exit /b 0
:fail
echo [失败] 服务未运行时无法在线备份。可停止服务后直接复制整个 data 文件夹。
popd
pause
exit /b 1
