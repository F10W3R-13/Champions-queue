@echo off
setlocal enabledelayedexpansion
title CQ - Push to GitHub

REM ================================================================
REM  Champion's Queue - Push to private GitHub repo
REM  Prerequisite: _setup_git_and_commit.bat already completed.
REM  ASCII-only (safe on any Windows locale).
REM ================================================================

echo.
echo ============================================================
echo   Champion's Queue - Push to GitHub
echo ============================================================
echo.
echo Did you already run _setup_git_and_commit.bat?
echo   Y = yes, this is my 2nd step
echo   N = no, close this and run that one first
echo.
set "ANS="
set /p ANS="   Already committed? (Y/N): "
if /i not "!ANS!"=="Y" (
    echo.
    echo Please run _setup_git_and_commit.bat first.
    echo.
    pause
    exit /b 0
)

cd /d "C:\Users\0616y\Downloads\Champion's Queue"

echo.
echo ============================================================
echo   Create a PRIVATE GitHub repo (do this in your browser)
echo ============================================================
echo.
echo   1. Go to https://github.com/new  (log in first)
echo   2. Repository name: champions-queue
echo   3. Description (optional): CODM invite-only ranked queue
echo   4. Visibility: choose Private  ^<-- IMPORTANT
echo   5. UNCHECK all boxes (no README, no .gitignore, no license)
echo   6. Click [Create repository]
echo.
echo   After creating, copy the URL from your browser address bar.
echo   Example: https://github.com/your-name/champions-queue
echo.
pause

set "REPO_URL="
set /p REPO_URL="   Paste the GitHub repo URL here: "
if "!REPO_URL!"=="" (
    echo.
    echo [ERROR] URL is empty. Run again.
    echo.
    pause
    exit /b 1
)

echo.
echo [1/3] Adding remote ...
git remote remove origin 2>nul
git remote add origin "!REPO_URL!.git"
if errorlevel 1 (
    echo.
    echo [ERROR] Could not add remote. Check the URL: !REPO_URL!
    echo.
    pause
    exit /b 1
)
echo       Done.

echo.
echo [2/3] Pushing to GitHub ...
echo   A login window may pop up - sign in with your browser.
echo.
git push -u origin main
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   Push FAILED. Common causes:
    echo   - GitHub sign-in not completed
    echo   - Typo in the repo URL
    echo   - The GitHub repo was not empty
    echo     (delete it on GitHub and create an empty one)
    echo ============================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   GitHub upload DONE!
echo ============================================================
echo.
echo Open !REPO_URL! in your browser and verify:
echo   [ ] .env is NOT visible  (most important!)
echo   [ ] CQ_Bot\cogs\ files are visible
echo   [ ] .blueprint.json files are visible
echo   [ ] Staff\*.docx files are visible
echo   [ ] champions_queue_status.md is visible
echo.
echo   If .env IS visible, delete it on GitHub right now
echo   and reset your Discord/Airtable/OpenAI keys.
echo.
pause
