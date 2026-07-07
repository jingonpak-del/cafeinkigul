@echo off
chcp 65001 >nul
cd /d C:\Users\USER\인기글
echo ============================================================
echo   인기글 트래커 - 전체 시작 (서버 + 고정주소 터널)
echo ============================================================
echo.
echo  [1/2] 인기글 서버 시작 (포트 8090)...
start "인기글 서버" cmd /k "cd /d C:\Users\USER\인기글 && python -m src.poc.server"
timeout /t 4 >nul
echo  [2/2] Cloudflare 고정주소 터널 시작...
start "인기글 터널" "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel run ingigeul
echo.
echo ============================================================
echo   완료!  접속 주소: https://dashboard.whitedr.com
echo          로그인: zumma / 123456
echo.
echo   * 열린 두 개의 창(서버/터널)을 닫지 마세요. 닫으면 중단됩니다.
echo   * 최소화해서 두시면 됩니다.
echo ============================================================
echo.
pause
