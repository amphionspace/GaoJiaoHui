@echo off
rem Booth launcher for Microsoft Edge on Windows.
rem Edge is Chromium based, so --kiosk-printing works the same way: window.print()
rem goes straight to the default printer without any dialog.
rem
rem Before using this file:
rem   1. Set EPSON L3350 as the default printer.
rem   2. Create an 80 x 170 mm form (Print Server Properties -> Forms) and make
rem      it the default paper size for that printer.
rem
rem Usage: double-click, or run: kiosk-print-edge.cmd [url]

setlocal
set "URL=%~1"
if "%URL%"=="" set "URL=https://amphion-gjh.amphiondev.com/"

set "PROFILE=%LOCALAPPDATA%\booth-edge"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" goto noedge

rem An already running Edge ignores new flags, so end it first.
taskkill /IM msedge.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

rem Drop --kiosk below if you want a windowed browser instead of fullscreen.
start "" "%EDGE%" --kiosk --kiosk-printing --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check --disable-pinch "%URL%"
goto :eof

:noedge
echo Microsoft Edge was not found.
echo Install Edge, then run this file again.
pause
