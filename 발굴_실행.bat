@echo off
REM ===================================================================
REM  Cafe discovery job - runs daily at 04:30 via Task Scheduler.
REM  Enumerates section APIs, probes the top unprobed candidates by
REM  reading sample article bodies, scores them by training value, and
REM  puts ~5 vetted cafes into the approval queue.
REM  Runs right after the 04:00 session-refresh job so cookies are fresh.
REM
REM  Log: D:\cafe-corpus\logs\discovery_YYYYMMDD.log (pruned after 14 days)
REM  Docs (Korean): C:\Users\USER\서브프로그램\네이버카페글모으기\PLAN.md
REM
REM  ASCII only on purpose. cmd reads .bat using the console code page,
REM  which differs between an interactive shell (65001) and Task
REM  Scheduler (949); Korean comments got mangled into stray command
REM  separators and broke the script. Keep this file ASCII.
REM ===================================================================
cd /d "%~dp0"
set PY=C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe
set PYTHONIOENCODING=utf-8
set LOGDIR=D:\cafe-corpus\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i
set LOG=%LOGDIR%\discovery_%TODAY%.log
echo.>> "%LOG%"
echo ===== %date% %time% discovery start =====>> "%LOG%"
REM -u = unbuffered, so the log is readable while the job is still running.
"%PY%" -u -m src.poc.discovery >> "%LOG%" 2>&1
echo ===== done (exit=%ERRORLEVEL%) =====>> "%LOG%"
