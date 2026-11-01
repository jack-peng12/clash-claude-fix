@echo off
call "%~dp0_common.bat" || exit /b 1
echo ==== 安装 全球现成公司供应商开发Agent ====

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo 已生成 .env，请用记事本修改其中的管理员密码后再次运行本脚本。
  notepad ".env"
)
if not exist "data" mkdir data

if exist "images\supplier-agent.tar" (
  echo 正在从安装包导入镜像（离线安装）...
  docker load -i "images\supplier-agent.tar" || goto :fail
) else (
  echo 未找到离线镜像，正在联网构建...
  docker compose build || goto :fail
)

docker compose up -d agent || goto :fail

echo 正在开放局域网访问端口（需要管理员权限，失败可忽略后手动设置防火墙）...
netsh advfirewall firewall delete rule name="SupplierAgent" >nul 2>&1
netsh advfirewall firewall add rule name="SupplierAgent" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1

echo.
echo 安装完成。本机访问: http://localhost:8000
echo 局域网内其他员工访问: http://本机IP:8000  （本机IP见下方 IPv4 地址）
ipconfig | findstr /i "IPv4"
echo.
echo 请在 Docker Desktop 设置中勾选 "Start Docker Desktop when you sign in"，以便开机后自动运行。
start "" http://localhost:8000
popd
pause
exit /b 0

:fail
echo [失败] 安装未完成，请把上面的错误信息截图发给技术支持。
popd
pause
exit /b 1
