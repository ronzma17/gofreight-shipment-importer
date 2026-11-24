@echo off
chcp 65001 >nul
cd /d "%~dp0"

:menu
cls
echo ============================================================
echo   GoFreight  -  create ocean import shipments
echo ============================================================
echo.
echo   FIRST TIME ONLY
echo     1 = Check API key        (read only)
echo     2 = Look up refs         (read only)
echo.
echo   EVERY BATCH
echo     3 = Report xlsx  -^>  shipments.csv
echo     4 = Preview              (nothing is sent)
echo     5 = CREATE FOR REAL
echo.
echo     6 = Open push_log.csv
echo     0 = Quit
echo.
set /p c="Type a number then Enter: "
if "%c%"=="1" goto check
if "%c%"=="2" goto refs
if "%c%"=="3" goto convert
if "%c%"=="4" goto preview
if "%c%"=="5" goto create
if "%c%"=="6" goto log
if "%c%"=="0" exit
goto menu

:check
echo.
python check.py
echo.
pause
goto menu

:refs
echo.
echo --- offices (office_ref) ---
python lookup.py offices
echo.
echo --- container sizes ---
python lookup.py sizes
echo.
echo --- package units ---
python lookup.py packages
echo.
pause
goto menu

:convert
cls
echo.
echo Drag the report file into this window, then press Enter.
set "xlsx="
set /p xlsx="Report xlsx: "
if not defined xlsx goto menu
echo.
set "eta="
set /p eta="ETA  (2026-12-05  or  12/05/2026): "
if not defined eta echo ETA is required. && pause && goto menu
echo.
echo Vessel name is read from the report automatically.
echo Leave the next line empty unless it comes out wrong.
set "vsl="
set /p vsl="Vessel name (press Enter to skip): "
echo.
echo ------------------------------------------------------------
echo   The GoFreight sandbox is SHARED with other customers.
echo   Anonymizing keeps real B/L numbers, parties and cargo
echo   descriptions out of it. Container counts, ports, sizes,
echo   weights and volumes are kept as they are.
echo ------------------------------------------------------------
set "anon=Y"
set /p anon="Anonymize?  Y = yes (sandbox)   n = no (real data): "
set "FLAG=--anonymize"
if /i "%anon%"=="n" set "FLAG="
echo.
python from_report.py %xlsx% --eta "%eta%" --vessel "%vsl%" %FLAG% -o shipments.csv
echo.
pause
goto menu

:preview
echo.
if not exist shipments.csv echo No shipments.csv yet - run 3 first. && pause && goto menu
python push.py shipments.csv > preview.txt 2>&1
echo Preview written to preview.txt
start "" notepad preview.txt
echo.
pause
goto menu

:create
cls
echo ============================================================
echo   THIS CREATES SHIPMENTS IN GOFREIGHT FOR REAL
echo ============================================================
echo.
if not exist shipments.csv echo No shipments.csv yet - run 3 first. && pause && goto menu
echo   This cannot be undone from here. Deleting them afterwards
echo   means doing it by hand in the GoFreight web UI.
echo.
echo   Did you run 4 and read the preview?
echo   Is shipments.csv anonymized, if this is the sandbox?
echo.
set "ok="
set /p ok="Type  GO  to continue, anything else to go back: "
if /i not "%ok%"=="GO" goto menu
echo.
python push.py shipments.csv --go
echo.
pause
goto menu

:log
if not exist push_log.csv echo No push_log.csv yet. && pause && goto menu
start "" push_log.csv
goto menu
