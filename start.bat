@echo off
:: Event-App starten (Backend + Frontend)
:: Erreichbar im LAN unter http://<DEINE-LAN-IP>:3000

echo Event-App wird gestartet...
echo.

:: Prüfe ob Docker DB läuft
docker-compose -f "%~dp0docker-compose.yml" ps db 2>nul | findstr "healthy" >nul
if errorlevel 1 (
    echo Starte PostgreSQL...
    docker-compose -f "%~dp0docker-compose.yml" up -d db
    timeout /t 5 /nobreak >nul
)

:: Backend starten
echo Starte Backend auf Port 8000...
start "Event-App Backend" /MIN cmd /c "cd /d %~dp0backend && uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

:: Frontend starten
echo Starte Frontend auf Port 3000...
start "Event-App Frontend" /MIN cmd /c "cd /d %~dp0frontend && npx next dev --hostname 0.0.0.0 --port 3000"
timeout /t 5 /nobreak >nul

echo.
echo ========================================
echo   Event-App laeuft!
echo   PC:     http://localhost:3000
echo   iPhone: http://<DEINE-LAN-IP>:3000
echo   Admin:  http://localhost:3000/admin
echo ========================================
echo.
echo Druecke eine Taste zum Beenden...
pause >nul

:: Beim Beenden Server stoppen
taskkill /F /IM uvicorn.exe >nul 2>&1
taskkill /F /FI "WindowTitle eq Event-App Frontend" >nul 2>&1
echo Server gestoppt.
