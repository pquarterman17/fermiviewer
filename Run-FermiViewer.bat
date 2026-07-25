@echo off
setlocal

pushd "%~dp0" || exit /b 1

where uv >nul 2>nul
if errorlevel 1 (
    echo FermiViewer could not start because uv is not installed or is not on PATH.
    echo Install uv from https://docs.astral.sh/uv/ and try again.
    popd
    pause
    exit /b 1
)

uv run fv %*
set "FERMIVIEWER_EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %FERMIVIEWER_EXIT_CODE%
