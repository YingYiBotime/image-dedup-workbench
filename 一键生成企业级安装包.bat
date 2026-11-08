@echo off
chcp 65001 >nul
title EVE_IDT — 一键编译企业级 Windows 安装向导 (Eve_image_dedup_tool)
cd /d "%~dp0"

set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

echo ========================================================================
echo   正在为您构建商业级 Windows 安装包向导 (EVE_IDT_Setup.exe)
echo   特性集成：
echo   1. 资源管理器文件夹右键菜单快速查重关联（带应用矢量图标）；
echo   2. 桌面快捷方式与开始菜单快捷方式；
echo   3. 开机自启（可选勾选）；
echo   4. Windows 控制面板标准卸载程序（卸载时可选择保留用户暂存区）；
echo   5. 进程内核互斥锁防并发保护。
echo ========================================================================
echo.

rem 1. 检查便携版基础文件是否存在
if not exist "%~dp0dist_portable\EVE_IDT\EVE_IDT.exe" (
    echo [1/2] 检测到尚未生成便携版主程序，正在自动调用 PyInstaller 打包...
    call "%~dp0一键生成免安装绿色版.bat"
) else (
    echo [1/2] 便携版核心文件已就绪 (dist_portable\EVE_IDT\EVE_IDT.exe)
)

rem 2. 查找 Inno Setup 编译器
set "ISCC_EXE="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_EXE=C:\Program Files\Inno Setup 6\ISCC.exe"

if "%ISCC_EXE%"=="" (
    echo [错误] 未在默认路径找到 Inno Setup 6 编译器 (ISCC.exe)！
    pause
    exit /b 1
)

echo.
echo [2/2] 正在调用 Inno Setup 6 编译企业级安装包向导 (LZMA2 Ultra 极速压缩)...
"%ISCC_EXE%" "%~dp0installer.iss"

if %errorlevel% neq 0 (
    echo.
    echo [错误] Inno Setup 编译失败，请检查上方日志。
    pause
    exit /b %errorlevel%
)

echo.
echo ========================================================================
echo   企业级安装向导打包成功！
echo   输出目录：%~dp0dist_installer
echo ========================================================================
explorer "%~dp0dist_installer"
pause
