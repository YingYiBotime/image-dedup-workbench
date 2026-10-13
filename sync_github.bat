@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ======================================================
echo    Image Dedup Workbench - GitHub 同步与热更新助手
echo ======================================================
echo.

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [错误] 当前目录尚未初始化为 Git 仓库！
    pause
    exit /b 1
)

echo 当前变更状态:
echo ------------------------------------------------------
git status -s
echo ------------------------------------------------------
echo.

set /p msg="请输入本次提交的更新说明 (直接回车默认: Update Image Dedup Workbench): "
if "%msg%"=="" set msg=Update Image Dedup Workbench

echo.
echo [1/4] 正在生成签名热更新补丁包 (ota_hotpatch.zip ^& version.json)...
python publish_github_update.py --no-push --notes "%msg%"

echo [2/4] 正在添加所有变更文件...
git add .

echo [3/4] 正在提交本地版本...
git commit -m "%msg%"

echo [4/4] 正在推送到 GitHub 远程仓库 (main 分支)...
git push -u origin main

if errorlevel 1 (
    echo.
    echo [警告] 推送可能失败，请检查网络连接或 GitHub 凭据。
) else (
    echo.
    echo [成功] 已成功同步推送到 GitHub（所有客户端打开软件将自动秒级同步更新）！
)

echo.
pause
