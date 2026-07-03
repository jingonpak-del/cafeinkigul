@echo off
chcp 65001 >nul
echo ============================================================
echo   인기글 트래커 - 사내 공유용 방화벽 열기 (TCP 8000)
echo ============================================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] 관리자 권한이 필요합니다.
  echo     이 파일을 마우스 우클릭 - "관리자 권한으로 실행" 해주세요.
  echo.
  pause
  exit /b
)

netsh advfirewall firewall delete rule name="IngigeulTracker8000" >nul 2>&1
netsh advfirewall firewall add rule name="IngigeulTracker8000" dir=in action=allow protocol=TCP localport=8000

echo.
echo [완료] 방화벽에서 8000 포트가 열렸습니다.
echo.
echo  동료들에게 아래 주소를 공유하세요:
echo.
echo      http://10.214.232.74:8000
echo.
echo  (주의: 이 PC가 켜져 있고 서버가 실행 중이어야 보입니다.)
echo  (주의: 이 PC의 IP가 바뀌면 주소도 바뀝니다.)
echo.
pause
