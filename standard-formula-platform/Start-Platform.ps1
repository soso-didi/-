param([string]$PagePath = "/")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root "runtime\python\python.exe"
if (-not (Test-Path $python)) { throw "缺少便携 Python：$python。请按 README 复制 runtime 目录。" }
$logRoot = Join-Path $env:TEMP "standard-formula-platform-logs"
if (-not (Test-Path $logRoot)) { New-Item -ItemType Directory -Path $logRoot | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logOut = Join-Path $logRoot "server-$stamp.out.log"
$logErr = Join-Path $logRoot "server-$stamp.err.log"
try { $null = Invoke-RestMethod "http://127.0.0.1:8010/api/health" -TimeoutSec 2 } catch {
  Start-Process -FilePath $python -ArgumentList @("-m", "backend.app") -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr
  Start-Sleep -Seconds 2
}
Start-Process "http://127.0.0.1:8010$PagePath"
