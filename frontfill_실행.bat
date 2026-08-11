@echo off
REM ===================================================================
REM  Frontfill job - captures NEW posts across ALL boards of crawl_all
REM  cafes via article_id head-advance. Scans last_seen_id+1 .. head,
REM  so it is cheap and covers every board without per-board polling.
REM  First run per cafe just seeds the cursor at head (collects 0);
REM  later runs collect the gap. Run FREQUENTLY (e.g. every 20 min).
REM
REM  Requests come from the shared per-account budget and yield to the
REM  live stream watcher, so real-time collection is never starved.
REM  Per-cafe cursors live in frontfill_cursor (resume-safe).
REM
REM  Log: D:\cafe-corpus\logs\frontfill_YYYYMMDD.log (pruned after 14 days)
REM  ASCII only on purpose (cmd mangles bat lines that contain non-ASCII).
REM ===================================================================
cd /d "%~dp0"
set PY=C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe
set PYTHONIOENCODING=utf-8
set LOGDIR=D:\cafe-corpus\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i
set LOG=%LOGDIR%\frontfill_%TODAY%.log
echo.>> "%LOG%"
echo ===== %date% %time% frontfill start =====>> "%LOG%"
REM -u = unbuffered so the log updates live. 0.5h cap is a safety stop;
REM a normal frequent run finishes in seconds (only the new-id gap).
"%PY%" -u -m src.poc.frontfill run --max-hours 0.5 >> "%LOG%" 2>&1
echo ===== done (exit=%ERRORLEVEL%) =====>> "%LOG%"
"%PY%" -u -m src.poc.frontfill status >> "%LOG%" 2>&1
