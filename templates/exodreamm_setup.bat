@echo off
setlocal
for %%I in ("%~dp0.") do set GameDir=%%~nxI

:MENU
cls
echo ========================================
echo              %GameDir% Setup
echo ========================================
echo.

if exist "%~dp0!uninstall.list" (
    goto :MENU_INSTALLED
) else (
    goto :MENU_NOT_INSTALLED
)

:MENU_INSTALLED
echo Status: Game is INSTALLED
echo.
echo [U] Uninstall (Delete unzipped files)
echo [R] Re-install (Overwrite)
echo [E] Exit
echo.
choice /c URE /m "Select an option"
if errorlevel 3 goto :EXIT_SCRIPT
if errorlevel 2 goto :INSTALL
if errorlevel 1 goto :UNINSTALL
goto :MENU

:MENU_NOT_INSTALLED
echo Status: Game is NOT INSTALLED
echo.
echo [I] Install (Unzip archive)
echo [E] Exit
echo.
choice /c IE /m "Select an option"
if errorlevel 2 goto :EXIT_SCRIPT
if errorlevel 1 goto :INSTALL
goto :MENU

:UNINSTALL
echo.
echo Uninstalling %GameDir%...
if exist "%~dp0!uninstall.list" (
    powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; Get-Content '%~dp0!uninstall.list' | Sort-Object -Descending | ForEach-Object { if ($_ -ne '%GameDir%/' -and $_ -ne '%GameDir%') { $p = Join-Path '%~dp0..' $_; if (Test-Path $p) { Remove-Item $p -Recurse:$false -Force } } }; Remove-Item '%~dp0!uninstall.list' -Force"
)
echo Done. The original archive and metadata have been preserved.
pause
goto :MENU

:INSTALL
echo.
echo Installing %GameDir%...
"${util_dir}\unzip" -Z1 "${game_zip_path}" > "%~dp0!uninstall.list"
"${util_dir}\unzip" -o "${game_zip_path}" -d "%~dp0.."
echo Done. You can now launch %GameDir%.
pause
goto :MENU

:EXIT_SCRIPT
endlocal
exit /b 0
