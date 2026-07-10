# Ingigeul tracker keepalive - restart server(8090)/tunnel if down
# (ASCII-only: Korean path handled via $PSScriptRoot to avoid encoding issues)
$ErrorActionPreference = "SilentlyContinue"
$proj   = $PSScriptRoot
$py     = "C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe"
$cfd    = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$logdir = Join-Path $proj "data"
$log    = Join-Path $logdir "keepalive.log"

function Log($m) { Add-Content -Path $log -Value ("{0}  {1}" -f (Get-Date -Format "MM-dd HH:mm:ss"), $m) }

# single instance per session
$mutex = New-Object System.Threading.Mutex($false, "IngigeulKeepalive")
if (-not $mutex.WaitOne(0)) { exit }

if (-not (Test-Path $py)) { $py = "python" }
Log "keepalive start (proj=$proj)"

while ($true) {
  # 1) server on port 8090
  if (-not (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $py -ArgumentList "-m", "src.poc.server", "--port", "8090" `
      -WorkingDirectory $proj -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $logdir "server.out.log") `
      -RedirectStandardError  (Join-Path $logdir "server.err.log")
    Log "server 8090 was down -> restarted"
    Start-Sleep -Seconds 6
  }
  # 2) cloudflared tunnel
  if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $cfd -ArgumentList "tunnel", "run", "ingigeul" -WindowStyle Hidden
    Log "tunnel was down -> restarted"
    Start-Sleep -Seconds 6
  }
  Start-Sleep -Seconds 30
}
