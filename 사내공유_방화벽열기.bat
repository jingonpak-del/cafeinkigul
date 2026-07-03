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
echo  현재 이 PC의 접속 주소 후보 (사무실 LAN 주소를 동료에게 공유하세요):
echo.
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.*'} | ForEach-Object { '      http://' + $_.IPAddress + ':8000   (' + $_.InterfaceAlias + ')' }"
echo.
echo  * 보통 192.168.x.x 또는 10.x.x.x 형태가 사무실 LAN 주소입니다.
echo  * 이 PC가 켜져 있고 서버(python -m src.poc.server)가 실행 중이어야 보입니다.
echo  * 테더링/랜선을 바꾸면 IP가 바뀌니, 이 파일을 다시 실행해 주소를 확인하세요.
echo.
pause
