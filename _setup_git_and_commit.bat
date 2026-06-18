@echo off
setlocal enabledelayedexpansion
title CQ - First Commit

REM ================================================================
REM  Champion's Queue - First Commit Automation
REM  Double-click to run. ASCII-only (safe on any Windows locale).
REM ================================================================

echo.
echo ============================================================
echo   Champion's Queue - First Commit
echo ============================================================
echo.
echo This script will:
echo   1. Remove the old empty CQ_Bot\.git (no commits, no loss)
echo   2. Initialize a new git repo in the parent folder
echo   3. Delete the Windows junk file 'nul'
echo   4. Verify .env will NOT be committed (safety check)
echo   5. Commit all files
echo.
echo IMPORTANT: Your .env (with secrets) is NEVER committed.
echo.
echo Press any key to start, or close this window to cancel.
pause >nul

REM ---- 0. Go to project folder ----
set "PROJECT_DIR=C:\Users\0616y\Downloads\Champion's Queue"
cd /d "%PROJECT_DIR%"
if errorlevel 1 (
    echo.
    echo [ERROR] Folder not found: %PROJECT_DIR%
    echo.
    pause
    exit /b 1
)
echo.
echo [OK] Working folder: %CD%

REM ---- 1. Remove old empty .git ----
echo.
echo [1/6] Removing old CQ_Bot\.git ...
if exist "CQ_Bot\.git" (
    rmdir /s /q "CQ_Bot\.git"
    if exist "CQ_Bot\.git" (
        echo.
        echo [WARN] Could not delete .git folder.
        echo Please close any program using it and retry.
        echo.
        pause
        exit /b 1
    )
    echo       Done.
) else (
    echo       No old .git found - skipped.
)

REM ---- 2. Init new repo ----
echo.
echo [2/6] Initializing new git repo (branch: main) ...
git init -b main
if errorlevel 1 (
    echo.
    echo [ERROR] git init failed. Is git installed?
    echo.
    pause
    exit /b 1
)
echo       Done.

REM ---- 3. Set commit identity ----
echo.
echo [3/6] Set your commit identity.
echo.
echo   Type your NAME (e.g. Hong Gildong) and press Enter.
echo   Use the same email you will use on GitHub.
echo.
set "GIT_NAME="
set "GIT_EMAIL="
set /p GIT_NAME="   Your name: "
set /p GIT_EMAIL="   Your email: "
if "!GIT_NAME!"=="" set "GIT_NAME=CQ Owner"
if "!GIT_EMAIL!"=="" set "GIT_EMAIL=cq-owner@example.com"

git config user.name "!GIT_NAME!"
git config user.email "!GIT_EMAIL!"
echo.
echo       Identity set: !GIT_NAME! ^<!GIT_EMAIL!^>

REM ---- 4. Delete junk nul file ----
echo.
echo [4/6] Deleting Windows junk file 'nul' ...
if exist "CQ_Bot\nul" (
    del "CQ_Bot\nul" 2>nul
)
echo       Done.

REM ---- 5. Verify .env is ignored ----
echo.
echo [5/6] Verifying .env is ignored ...
set "ENV_SAFE=0"
set "ENV_OUTPUT="
for /f "delims=" %%i in ('git check-ignore .env CQ_Bot\.env 2^>nul') do (
    echo       Ignored: %%i
    set "ENV_SAFE=1"
)
if "!ENV_SAFE!"=="0" (
    echo.
    echo ============================================================
    echo   [STOP] .env is NOT ignored!
    echo   Committing would leak your secret keys.
    echo   Script stopped. Contact support.
    echo ============================================================
    echo.
    pause
    exit /b 1
)
echo       OK - .env will NOT be committed.

REM ---- 6. Stage and commit ----
echo.
echo [6/6] Staging all files and committing ...
echo.
echo   --- Files about to be committed ---
echo   (.env should NOT appear below)
echo.
git add -A
git status --short
echo.
echo   ^>^> Look at the list above. If you see .env anywhere,
echo      close this window NOW (Ctrl+C) and contact support.
echo      If .env is absent, press any key to commit.
pause >nul

git commit -m "Initial commit: CQ Bot + project docs"
if errorlevel 1 (
    echo.
    echo [ERROR] Commit failed.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Local commit DONE!
echo ============================================================
echo.
git log --oneline
echo.
echo Next step: create a private GitHub repo, then run
echo   _push_to_github.bat
echo.
pause
