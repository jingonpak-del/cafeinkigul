@echo off
REM ===================================================================
REM  Backfill job - starts daily at 00:10, stops at 07:50 (8h cap).
REM  Walks article_id backwards from the newest known post, fetching
REM  bodies and comments. Per-cafe cursors live in the DB so an
REM  interrupted run resumes the next night. Requests come from the
REM  shared per-account budget but yield to the live stream watcher
REM  (RESERVE_BACKFILL), so real-time collection is never starved.
REM
REM  Log: D:\cafe-corpus\logs\backfill_YYYYMMDD.log (pruned after 14 days)
REM  Docs (Korean): C:\Users\USER\서브프로그램\네이버카페글모으기\PLAN.md
REM
REM  ASCII only on purpose - see 발굴_실행.bat for why.
REM ===================================================================
cd /d "%~dp0"
set PY=C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe
set PYTHONIOENCODING=utf-8
set LOGDIR=D:\cafe-corpus\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i
set LOG=%LOGDIR%\backfill_%TODAY%.log
echo.>> "%LOG%"
echo ===== %date% %time% backfill start =====>> "%LOG%"
REM -u = unbuffered. Without it a multi-hour run writes nothing to the log
REM until it exits, so you cannot tell a working job from a hung one.
"%PY%" -u -m src.poc.backfill run --until 07:50 --max-hours 8 >> "%LOG%" 2>&1
echo ===== done (exit=%ERRORLEVEL%) =====>> "%LOG%"
"%PY%" -u -m src.poc.backfill status >> "%LOG%" 2>&1
