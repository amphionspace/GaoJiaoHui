@echo off
rem Booth launcher for Windows.
rem Starts Chrome with --kiosk-printing so window.print() goes straight to the
rem default printer without the print dialog.
rem
rem Before using this file:
rem   1. Set EPSON L3350 as the default printer.
rem   2. Create an 80 x 170 mm form (Print Server Properties -> Forms) and make
rem      it the default paper size for that printer.
rem   3. Close Chrome completely once; this script kills it anyway.
rem
rem Usage: double-click, or run: kiosk-print.cmd [url]

setlocal
set "URL=%~1"
if "%URL%"=="" set "URL=https://amphion-gjh.amphiondev.com/"

set "PROFILE=%LOCALAPPDATA%\booth-chrome"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" goto nochrome

rem An already running Chrome ignores new flags, so end it first.
taskkill /IM chrome.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

rem Drop --kiosk below if you want a windowed browser instead of fullscreen.
start "" "%CHROME%" --kiosk --kiosk-printing --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check --disable-pinch "%URL%"
goto :eof

:nochrome
echo Google Chrome was not found.
echo Install Chrome, then run this file again.
pause
