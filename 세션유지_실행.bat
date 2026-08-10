@echo off
REM 유휴 계정 네이버 세션 유지 (매일 04:00, 작업 스케줄러 등록)
REM 30일 넘게 안 쓰인 계정은 세션이 만료돼 죽는다. 가벼운 열람 요청으로 만료를 다시 민다.
REM 로그: C:\Users\USER\svc\logs\keepalive.log
cd /d "%~dp0"
set PY=C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe
echo. >> "C:\Users\USER\svc\logs\keepalive.log"
echo ===== %date% %time% ===== >> "C:\Users\USER\svc\logs\keepalive.log"
"%PY%" -m src.poc.keepalive >> "C:\Users\USER\svc\logs\keepalive.log" 2>&1
