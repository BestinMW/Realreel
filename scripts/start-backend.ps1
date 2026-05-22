Set-Location $PSScriptRoot\..\backend

$existing = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    Stop-Process -Id $existing.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep 1
    Write-Host "Stopped previous process on port 8000."
}

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
& $python -m pip install -q -r requirements.txt
Write-Host "Starting backend at http://127.0.0.1:8000 (health should show version 2026-05-22)"
& $python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
