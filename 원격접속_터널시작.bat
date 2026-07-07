@echo off
chcp 65001 >nul
echo ============================================================
echo   인기글 트래커 - 고정주소 터널 (dashboard.whitedr.com)
echo ============================================================
echo.
echo  이 창을 켜둔 채로 두면 https://dashboard.whitedr.com 로 접속됩니다.
echo  (인기글 서버(python -m src.poc.server)도 함께 켜져 있어야 함)
echo.
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel run ingigeul
pause
