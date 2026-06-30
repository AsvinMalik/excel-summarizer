:: Quick Test Script - Verify Everything Works
:: Run this after starting both servers to test the system

@echo off
REM Colors: 
REM 2=green, 4=red, 6=yellow, 7=white, 8=gray

echo.
echo ============================================
echo   SYSTEM STATUS CHECK
echo ============================================
echo.

REM Test Backend Health
echo Checking Backend...
for /f %%A in ('powershell -Command "try { (Invoke-WebRequest -Uri 'http://localhost:8000/health' -UseBasicParsing).StatusCode } catch { echo 'ERROR' }"') do set backend_status=%%A

if "%backend_status%"=="200" (
  echo [OK] Backend is running on http://localhost:8000
) else (
  echo [FAIL] Backend is NOT responding. Start it with: START_BACKEND.bat
)

REM Test Frontend
echo.
echo Checking Frontend...
for /f %%A in ('powershell -Command "try { (Invoke-WebRequest -Uri 'http://localhost:4173' -UseBasicParsing).StatusCode } catch { echo 'ERROR' }"') do set frontend_status=%%A

if "%frontend_status%"=="200" (
  echo [OK] Frontend is running on http://localhost:4173
) else (
  echo [FAIL] Frontend is NOT responding. Start it with: START_FRONTEND.bat
  echo Trying alternate port 4174...
  for /f %%A in ('powershell -Command "try { (Invoke-WebRequest -Uri 'http://localhost:4174' -UseBasicParsing).StatusCode } catch { echo 'ERROR' }"') do set frontend_status=%%A
  if "%frontend_status%"=="200" (
    echo [OK] Frontend is running on http://localhost:4174
  )
)

echo.
echo ============================================
echo.

if "%backend_status%"=="200" if "%frontend_status%"=="200" (
  echo SUCCESS! System is fully operational.
  echo.
  echo Open your browser:
  echo http://localhost:4173 (or 4174)
  echo.
) else (
  echo Please ensure both servers are running:
  echo   1. START_BACKEND.bat  (Terminal 1)
  echo   2. START_FRONTEND.bat (Terminal 2)
)

echo.
pause
