@echo off
setlocal
title Pigeon - Claude Code
cd /d "%~dp0"

rem The server runs in its own minimised window and opens the page in the
rem browser. This window becomes a Claude Code session in the same folder, so
rem the terminal and the pane in the page work on the same contacts.
start "PigeonServer" /min cmd /c "python serve.py"

where claude >nul 2>nul
if errorlevel 1 goto noclaude

echo.
echo   Pigeon is opening in your browser at http://localhost:8642/
echo.
echo   This window is Claude Code, already sitting in the Pigeon folder.
echo   Ask for a change here, or use the Claude Code button in the page.
echo.
call claude --permission-mode acceptEdits
goto stop

:noclaude
echo.
echo   Pigeon is opening in your browser at http://localhost:8642/
echo.
echo   The claude command is not on PATH, so this window cannot start a
echo   session. The page works without it.
echo.
echo   Press any key to stop Pigeon.
pause >nul

:stop
rem Take the server down with this window. serve.py writes its own pid, so give
rem it a moment in case this window was closed the instant it opened.
timeout /t 2 /nobreak >nul 2>nul
if exist ".pigeon-server.pid" (
  for /f "usebackq delims=" %%p in (".pigeon-server.pid") do taskkill /f /pid %%p >nul 2>nul
  del ".pigeon-server.pid" >nul 2>nul
)
taskkill /f /fi "WINDOWTITLE eq PigeonServer*" >nul 2>nul
echo.
echo   Pigeon stopped.
