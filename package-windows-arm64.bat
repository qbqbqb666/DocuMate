@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" || goto :failed

set "NPM_CONFIG_REGISTRY=https://registry.npmmirror.com/"
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/"
set "UV_DEFAULT_INDEX=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/"
set "UV_PYTHON_INSTALL_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone/"

where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo Node.js/npm was not found in PATH.
    goto :failed
)
py -3.14 -m uv --version >nul 2>&1
if errorlevel 1 (
    echo Native ARM64 Python 3.14 with the uv module was not found.
    goto :failed
)

echo Installing Node.js dependencies...
call npm.cmd ci --include=dev
if errorlevel 1 goto :failed

echo Building DocuMate for Windows ARM64...
call npm.cmd run package:win:arm64
if errorlevel 1 goto :failed

if not exist "release\windows-arm64\latest.yml" goto :failed
echo.
echo Build succeeded. Files are in release\windows-arm64\
goto :success

:failed
echo.
echo Build failed. Review the error above.
set "result=1"
goto :done

:success
set "result=0"

:done
popd
pause
exit /b %result%
