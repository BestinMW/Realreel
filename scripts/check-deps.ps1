$tools = @("ffmpeg", "yt-dlp", "tesseract", "python")
$missing = @()

foreach ($tool in $tools) {
    if (Get-Command $tool -ErrorAction SilentlyContinue) {
        Write-Host "[ok] $tool"
    } else {
        Write-Host "[missing] $tool"
        $missing += $tool
    }
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Install on Windows (winget):"
    Write-Host "  winget install Gyan.FFmpeg"
    Write-Host "  winget install yt-dlp.yt-dlp"
    Write-Host "  winget install UB-Mannheim.TesseractOCR"
    Write-Host ""
    Write-Host "Restart the terminal after installing, then run scripts/check-deps.ps1 again."
    exit 1
}

Write-Host ""
Write-Host "All tools found. Start backend and frontend:"
Write-Host "  scripts/start-backend.ps1"
Write-Host "  scripts/start-frontend.ps1"
