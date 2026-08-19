param([string]$PagePath = "/")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root "runtime\python\python.exe"
if (-not (Test-Path $python)) { throw "缺少便携 Python：$python。请按 README 复制 runtime 目录。" }
if (-not (Test-Path (Join-Path $root "logs"))) { New-Item -ItemType Directory -Path (Join-Path $root "logs") | Out-Null }
try { $null = Invoke-RestMethod "http://127.0.0.1:8010/api/health" -TimeoutSec 2 } catch {
  Start-Process -FilePath $python -ArgumentList "-m backend.app" -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root "logs\server.out.log") -RedirectStandardError (Join-Path $root "logs\server.err.log")
  Start-Sleep -Seconds 2
}
Start-Process "http://127.0.0.1:8010$PagePath"
