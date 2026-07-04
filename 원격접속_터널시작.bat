@echo off
chcp 65001 >nul
echo ============================================================
echo   인기글 트래커 - 외부 접속용 Cloudflare Tunnel
echo ============================================================
echo.
echo  잠시 후 아래에 https://....trycloudflare.com 주소가 뜹니다.
echo  그 주소로 집/외부/폰에서 접속하세요.
echo.
echo  [주의]
echo   - 이 창을 닫으면 외부 접속이 끊깁니다 (창을 켜둔 채로 두세요).
echo   - 서버(python -m src.poc.server)도 함께 켜져 있어야 합니다.
echo   - 실행할 때마다 주소가 새로 바뀝니다 (무료 Quick Tunnel 특성).
echo.
echo ------------------------------------------------------------
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8090
pause
