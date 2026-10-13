@echo off
chcp 65001 >nul
cd /d "%~dp0"
git config --global http.sslBackend openssl >nul 2>&1
echo ======================================================
echo    图像智能查重工作台 - GitHub 一键授权与云端更新同步
echo    目标仓库: YingYiBotime/image-dedup-workbench
echo ======================================================
echo.

set /p msg="请输入本次更新说明 (直接按【回车键】使用默认说明并立即推送): "
if "%msg%"=="" set msg=Update Image Dedup Workbench

echo.
echo [1/3] 正在生成签名热更新清单 (version.json)...
python publish_github_update.py --no-push --notes "%msg%"

echo [2/3] 正在打包本地代码变更...
git add .
git commit -m "%msg%" >nul 2>&1

echo [3/3] 正在连接 GitHub (首次运行将自动弹出登录授权窗口)...
echo       -^> 请在弹出的窗口中点击【Sign in with your browser】完成授权！
echo.
git push -u origin main

if errorlevel 1 (
    echo.
    echo [提示] 推送未完成，请确认已在弹出的窗口中点击授权，或检查代理/网络。
) else (
    echo.
    echo ======================================================
    echo [成功] 已成功同步推送到 GitHub (YingYiBotime/image-dedup-workbench)！
    echo        现在所有用户打开软件都会自动收到更新提示并完成升级！
    echo ======================================================
)

echo.
pause
