@echo off
REM TactileSense DMR Studio - Easy Run Script

echo.
echo ========================================
echo Starting TactileSense DMR Studio...
echo ========================================
echo.

python tactile_sense_main_dmr.py

if %errorlevel% neq 0 (
    echo.
    echo ========================================
    echo ERROR: TactileSense DMR Studio failed to start
    echo ========================================
    echo.
    echo Run INSTALL_WINDOWS.bat first if you haven't already.
    echo.
    pause
)
