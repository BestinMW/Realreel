Set-Location $PSScriptRoot\..\backend

$lanIp = (
    Get-NetIPConfiguration -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPv4DefaultGateway -and
        $_.IPv4Address.IPAddress -match "^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)" -and
        $_.InterfaceAlias -notmatch "Radmin|VPN|VirtualBox|Loopback"
    } |
    Select-Object -First 1 -ExpandProperty IPv4Address
).IPAddress

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

$tesseract = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (Test-Path $tesseract) {
    $env:TESSERACT_CMD = $tesseract
    Write-Host "Tesseract: $tesseract"
} else {
    Write-Host "Tesseract not found. OCR will be skipped until you install it:"
    Write-Host "  winget install UB-Mannheim.TesseractOCR"
    Write-Host "Or set ENABLE_KEYFRAME_OCR=false in backend/.env.local"
}
Write-Host "Starting backend at http://0.0.0.0:8000 (health should show version 2026-05-22)"
if ($lanIp) {
    Write-Host "Other computers on the same network can check: http://$($lanIp):8000/health"
}
& $python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
